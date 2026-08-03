from __future__ import annotations

"""Curated evidence and calculations for the HDI B-track research package."""

from typing import Any


SOURCE_SPECS: list[dict[str, Any]] = [
    {
        "source_ref": "redboard_sse_reply",
        "source_file": "2025-10-21_上交所_红板科技_第二轮审核问询回复_HDI市场与份额.pdf",
        "title": "红板科技第二轮审核问询回复：HDI市场、份额与同业比较",
        "publisher": "上海证券交易所/红板科技",
        "publish_date": "2025-10-21",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "issuer_filing_with_third_party_market_data",
        "independence_key": "sse_redboard_inquiry_20251021",
        "independence_rationale": "上交所审核问询回复；市场数据引用Prismark/CPCA，发行人对自身份额存在利益相关。",
        "market_data_independence_key": "prismark_cpca_hdi_tables_quoted_by_redboard",
        "market_data_independence_rationale": "应用、份额与集中度来自问询回复转引的Prismark/CPCA表，不能与引用同一底层表的其他文件重复计为独立证据。",
    },
    {
        "source_ref": "victory_ar2025",
        "source_file": "胜宏科技2025年报.pdf",
        "title": "胜宏科技2025年年度报告",
        "publisher": "胜宏科技",
        "publish_date": "2026-03-13",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "victory_giant_ar2025",
        "independence_rationale": "公司经审计年度报告。",
    },
    {
        "source_ref": "victory_q1_2026",
        "source_file": "胜宏科技2026Q1.pdf",
        "title": "胜宏科技2026年第一季度报告",
        "publisher": "胜宏科技",
        "publish_date": "2026-04-27",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_filing",
        "independence_key": "victory_giant_q1_2026",
        "independence_rationale": "公司季度报告。",
    },
    {
        "source_ref": "victory_h_prospectus",
        "source_file": "胜宏科技H股.pdf",
        "title": "胜宏科技H股招股文件",
        "publisher": "胜宏科技/香港交易所",
        "publish_date": "2026-04-13",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "listing_document_with_commissioned_market_study",
        "independence_key": "victory_giant_hk_prospectus_2026",
        "independence_rationale": "港股招股文件；行业规模由受聘顾问Frost & Sullivan提供，需与Prismark交叉核验。",
    },
    {
        "source_ref": "pengding_ar2025",
        "source_file": "鹏鼎控股2025年报.pdf",
        "title": "鹏鼎控股2025年年度报告",
        "publisher": "鹏鼎控股",
        "publish_date": "2026-03-30",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "avary_ar2025",
        "independence_rationale": "公司经审计年度报告。",
    },
    {
        "source_ref": "pengding_q1_2026",
        "source_file": "鹏鼎控股2026Q1.pdf",
        "title": "鹏鼎控股2026年第一季度报告",
        "publisher": "鹏鼎控股",
        "publish_date": "2026-04-28",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_filing",
        "independence_key": "avary_q1_2026",
        "independence_rationale": "公司季度报告。",
    },
    {
        "source_ref": "kinwong_ar2025",
        "source_file": "景旺电子2025年报.pdf",
        "title": "景旺电子2025年年度报告",
        "publisher": "景旺电子",
        "publish_date": "2026-04-21",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "kinwong_ar2025",
        "independence_rationale": "公司经审计年度报告。",
    },
    {
        "source_ref": "kinwong_q1_2026",
        "source_file": "景旺电子2026Q1.pdf",
        "title": "景旺电子2026年第一季度报告",
        "publisher": "景旺电子",
        "publish_date": "2026-04-28",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_filing",
        "independence_key": "kinwong_q1_2026",
        "independence_rationale": "公司季度报告。",
    },
    {
        "source_ref": "shennan_ar2025",
        "source_file": "深南电路2025年报.pdf",
        "title": "深南电路2025年年度报告",
        "publisher": "深南电路",
        "publish_date": "2026-03-18",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing_with_prismark_table",
        "independence_key": "shennan_ar2025",
        "independence_rationale": "公司年报转载Prismark 2025Q4产品市场预测。",
        "market_data_independence_key": "prismark_2025q4_hdi_market",
        "market_data_independence_rationale": "市场规模与增速属于Prismark 2025Q4同一底层预测，不因出现在公司年报中成为新的独立市场证据。",
    },
    {
        "source_ref": "wus_ar2025",
        "source_file": "沪电股份2025年报.pdf",
        "title": "沪电股份2025年年度报告",
        "publisher": "沪电股份",
        "publish_date": "2026-03-25",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing_with_prismark_table",
        "independence_key": "wus_ar2025",
        "independence_rationale": "公司年报转载Prismark 2025Q4区域和产品预测。",
        "market_data_independence_key": "prismark_2025q4_hdi_market",
        "market_data_independence_rationale": "区域产值与增速属于Prismark 2025Q4同一底层预测，与深南电路年报中的同源表不构成第二条独立市场证据。",
    },
    {
        "source_ref": "gs_ai_pcb_tam",
        "source_file": (
            "2026-01-06_goldman sachs_电子_全球pcb：引入tam；2025-27年ai pcb_ccl"
            "价值将以+140%_+179%的复合年增长率增长；迈向m9 ccl、30+层pcb和"
            "6l hdi.pdf"
        ),
        "title": "Global PCB: Introducing TAM; toward 6L HDI",
        "publisher": "Goldman Sachs",
        "publish_date": "2026-01-06",
        "source_type": "website_material",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "sell_side_model",
        "independence_key": "goldman_ai_pcb_tam_20260106",
        "independence_rationale": "卖方自建AI PCB物量和价值量模型；用于需求拆解，不替代行业实际统计。",
    },
    {
        "source_ref": "nomura_victory_20260713",
        "source_file": (
            "2026-07-13_nomura_胜宏科技_胜宏科技（300476）：对产品延迟和市场份额"
            "流失的担忧过度…… ……rubin升级、asic和光收发器pcb是关键驱动力.pdf"
        ),
        "title": "Victory Giant: product delay and share-loss concerns are overdone",
        "publisher": "Nomura",
        "publish_date": "2026-07-13",
        "source_type": "website_material",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "recent_sell_side_model",
        "independence_key": "nomura_victory_20260713",
        "independence_rationale": "近期卖方预测与情景判断；不得作为客户认证的一手证明。",
    },
    {
        "source_ref": "yx_victory_20260709",
        "source_file": (
            "2026-07-09_甬兴证券_胜宏科技_胜宏科技（300476）：公司点评："
            "深耕高端pcb，受益于aipcb发展浪潮.pdf"
        ),
        "title": "胜宏科技：深耕高端PCB，受益于AI PCB发展浪潮",
        "publisher": "甬兴证券",
        "publish_date": "2026-07-09",
        "source_type": "website_material",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "recent_sell_side_model",
        "independence_key": "yongxing_victory_20260709",
        "independence_rationale": "近期卖方独立财务预测；仅用于外部模型对账，不作为客户认证或订单的一手证明。",
    },
    {
        "source_ref": "ubs_pengding_20260529",
        "source_file": (
            "2026-05-29_ubs equities_鹏鼎控股_鹏鼎控股（002938）：快评鹏鼎控股"
            "2026 aic： ai pcb新势力.pdf"
        ),
        "title": "Avary: an emerging AI PCB contender",
        "publisher": "UBS",
        "publish_date": "2026-05-29",
        "source_type": "website_material",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "recent_sell_side_model",
        "independence_key": "ubs_avary_20260529",
        "independence_rationale": "近期卖方预测和调研转述；客户名称及收入指引需降档使用。",
    },
    {
        "source_ref": "gf_pengding_20260630",
        "source_file": (
            "2026-06-30_广发证券_鹏鼎控股_鹏鼎控股（002938）：增资泰国子公司，"
            "高阶hdi及hlc扩产提速.pdf"
        ),
        "title": "鹏鼎控股：增资泰国子公司，高阶HDI及HLC扩产提速",
        "publisher": "广发证券",
        "publish_date": "2026-06-30",
        "source_type": "website_material",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "recent_sell_side_model",
        "independence_key": "gf_avary_20260630",
        "independence_rationale": "近期卖方财务模型；扩产事实需回到公司公告核验。",
    },
    {
        "source_ref": "cj_kinwong_20260628",
        "source_file": (
            "2026-06-28_长江证券_景旺电子_景旺电子（603228）：点评报告：聚焦ai"
            "算力与高端制造，深化1+1+n战略布局.pdf"
        ),
        "title": "景旺电子：聚焦AI算力与高端制造",
        "publisher": "长江证券",
        "publish_date": "2026-06-28",
        "source_type": "website_material",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "recent_sell_side_model",
        "independence_key": "cj_kinwong_20260628",
        "independence_rationale": "近期卖方财务模型；用作冻结后的外部对账。",
    },
    {
        "source_ref": "compeq_ar2024",
        "source_file": "2025-05-08_华通电脑_2024年报.pdf",
        "title": "华通电脑2024年年度报告",
        "publisher": "华通电脑",
        "publish_date": "2025-05-08",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_annual_report",
        "independence_key": "compeq_ar2024",
        "independence_rationale": "公司年度报告。",
    },
    {
        "source_ref": "meiko_ar2025",
        "source_file": "2025_Meiko_Annual_Report_2025.pdf",
        "title": "Meiko Annual Report 2025",
        "publisher": "Meiko Electronics",
        "publish_date": "2025-06-26",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_annual_report",
        "independence_key": "meiko_ar2025",
        "independence_rationale": "公司年度报告。",
    },
    {
        "source_ref": "zdt_ar2025",
        "source_file": "2026_臻鼎科技_2025_Annual_Report_EN.pdf",
        "title": "Zhen Ding Technology Annual Report 2025",
        "publisher": "Zhen Ding Technology",
        "publish_date": "2026-05-31",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_annual_report",
        "independence_key": "zdt_ar2025",
        "independence_rationale": "公司年度报告。",
    },
    {
        "source_ref": "ats_ar2025_26",
        "source_file": "2026_ATS_Annual_Report_2025_26.pdf",
        "title": "AT&S Annual Report 2025/26",
        "publisher": "AT&S",
        "publish_date": "2026-05-21",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_annual_report",
        "independence_key": "ats_ar2025_26",
        "independence_rationale": "公司年度报告。",
    },
    {
        "source_ref": "ttm_10k_2025",
        "source_url": (
            "https://investors.ttm.com/sec-filings/all-sec-filings/content/"
            "0001193125-26-051976/ttmi-20251229.htm"
        ),
        "title": "TTM Technologies 2025 Form 10-K",
        "publisher": "TTM Technologies/SEC",
        "publish_date": "2026-02-17",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_search",
        "is_primary_source": True,
        "source_credibility": "regulatory_filing",
        "independence_key": "ttm_10k_2025",
        "independence_rationale": "美国监管年报。",
    },
    {
        "source_ref": "ttm_hdi_product",
        "source_url": "https://www.ttm.com/en/solutions/printed-circuit-boards/hdi-pcb",
        "title": "TTM HDI PCBs & Microvia PCB Products",
        "publisher": "TTM Technologies",
        "publish_date": "2026-07-10",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_search",
        "is_primary_source": True,
        "source_credibility": "company_product_page",
        "independence_key": "ttm_hdi_product_page",
        "independence_rationale": "公司产品能力页；能够证明工艺能力，不能证明客户份额。",
    },
    {
        "source_ref": "ipc_4104",
        "source_url": "https://www.ipc.org/TOC/IPC-JPCA-4104.pdf",
        "title": "IPC/JPCA-4104 HDI and Microvia Materials",
        "publisher": "IPC",
        "publish_date": "1999-05-01",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_search",
        "is_primary_source": True,
        "source_credibility": "industry_standard",
        "independence_key": "ipc_jpca_4104",
        "independence_rationale": "行业标准原文；年代较早，仅用于定义，不用于当前市场判断。",
    },
    {
        "source_ref": "ipc_microvia_warning",
        "source_url": (
            "https://www.ipc.org/news-release/ipc-issues-electronics-industry-warning-"
            "printed-board-microvia-reliability-high"
        ),
        "title": "IPC warning on microvia reliability for high-performance products",
        "publisher": "IPC",
        "publish_date": "2019-03-06",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_search",
        "is_primary_source": True,
        "source_credibility": "industry_association_warning",
        "independence_key": "ipc_microvia_reliability_2019",
        "independence_rationale": "IPC技术警告；用于说明可靠性门槛，不代表所有产品必然失效。",
    },
    {
        "source_ref": "prismark_top100_2024",
        "source_url": (
            "https://www.prismark.com/_files/ugd/"
            "950e51_8ed1a31c4a2e405595e3f214995f9feb.pdf?index=true"
        ),
        "title": "Prismark 2024 Top 100 PCB Companies",
        "publisher": "Prismark Partners",
        "publish_date": "2025-11-01",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_search",
        "is_primary_source": False,
        "source_credibility": "specialist_industry_database",
        "independence_key": "prismark_top100_2024",
        "independence_rationale": "Prismark公开摘要；公司总收入包含非裸板和组装，不可当HDI份额。",
    },
    {
        "source_ref": "ats_patent_quality",
        "source_url": (
            "https://ats.net/en/press/fit-for-the-future-focus-on-patent-quality-"
            "takes-ats-on-the-top/"
        ),
        "title": "AT&S reports leading patent quality in HDI",
        "publisher": "AT&S",
        "publish_date": "2025-10-10",
        "source_type": "website_material",
        "quality_tier": 2,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_search",
        "is_primary_source": True,
        "source_credibility": "company_claim_with_named_analytics_provider",
        "independence_key": "ats_patent_quality_release",
        "independence_rationale": "公司新闻稿引用PatentSight；仅作为技术信号，不直接转化为份额或利润。",
    },
    {
        "source_ref": "zdt_huaian_investment",
        "source_url": (
            "https://www.zdtco.com/tw/news/%E6%96%B0%E8%81%9E%E9%9B%86%E9%8C%A6/"
            "%E8%87%BB%E9%BC%8E%E5%AD%90%E5%85%AC%E5%8F%B8%E9%B5%AC%E9%BC%8E"
            "%E6%8E%A7%E8%82%A1%E8%91%A3%E4%BA%8B%E6%9C%83%E9%80%9A%E9%81%8E"
            "%E6%B7%AE%E5%AE%89%E5%9C%92%E5%8D%80%E6%8A%95%E8%B3%87%E8%A8%88"
            "%E7%95%AB"
        ),
        "title": "臻鼎子公司淮安园区高阶PCB投资计划",
        "publisher": "臻鼎科技",
        "publish_date": "2025-08-01",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_search",
        "is_primary_source": True,
        "source_credibility": "company_release",
        "independence_key": "zdt_huaian_investment_2025",
        "independence_rationale": "公司投资公告。",
    },
    {
        "source_ref": "nvidia_gb200_userguide",
        "source_url": "https://docs.nvidia.com/dgx/dgxgb200-user-guide/dgxgb200-user-guide.pdf",
        "title": "NVIDIA DGX GB Rack Scale Systems User Guide",
        "publisher": "NVIDIA",
        "publish_date": "2026-05-01",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "official_platform_documentation",
        "independence_key": "nvidia_gb200_userguide",
        "independence_rationale": "NVIDIA官方硬件文档，用于核验整机、计算托盘和NVLink交换托盘数量；不披露PCB供应商和板级成本。",
    },
    {
        "source_ref": "trendforce_rubin_hdi",
        "source_url": "https://www.trendforce.com/presscenter/news/20251120-12790.html",
        "title": "Rubin’s Cableless Architecture and ASIC High-Layer HDI Designs Push PCBs to the Center of AI Compute Power",
        "publisher": "TrendForce",
        "publish_date": "2025-11-20",
        "source_type": "website_material",
        "quality_tier": 2,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": False,
        "source_credibility": "industry_research_with_platform_structure",
        "independence_key": "trendforce_rubin_hdi_20251120",
        "independence_rationale": "独立产业研究，用于识别Rubin架构中的24层HDI交换托盘和高层中板；属于前瞻判断，不能替代量产BOM。",
    },
    {
        "source_ref": "ttm_q1_2026",
        "source_url": (
            "https://investors.ttm.com/sec-filings/all-sec-filings/content/"
            "0001193125-26-191490/d103788dex991.htm"
        ),
        "title": "TTM Technologies 2026年第一季度业绩",
        "publisher": "TTM Technologies/SEC",
        "publish_date": "2026-04-29",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "regulatory_filing",
        "independence_key": "ttm_q1_2026_8k",
        "independence_rationale": "公司向SEC提交的8-K附件；GAAP与非GAAP口径分别保留。",
    },
    {
        "source_ref": "ats_fy2025_26_results",
        "source_url": (
            "https://ats.net/en/ir-news/"
            "ats-closes-successful-financial-year-with-strong-fourth-quarter/"
        ),
        "title": "AT&S 2025/26财年业绩与2026/27财年指引",
        "publisher": "AT&S",
        "publish_date": "2026-05-21",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_financial_release",
        "independence_key": "ats_fy2025_26_results",
        "independence_rationale": "公司正式年度业绩新闻稿和下一财年经营指引。",
    },
    {
        "source_ref": "twse_company_master_20260725",
        "source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        "title": "台湾证券交易所上市公司基本资料",
        "publisher": "台湾证券交易所",
        "publish_date": "2026-07-25",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "api_twse",
        "is_primary_source": True,
        "source_credibility": "official_exchange_api",
        "independence_key": "twse_company_master_20260725",
        "independence_rationale": "交易所官方上市公司基本资料；用于核验已发行普通股数量。",
    },
    {
        "source_ref": "twse_compeq_20260724",
        "source_url": (
            "https://www.twse.com.tw/rwd/en/afterTrading/BWIBBU?"
            "date=20260724&stockNo=2313&response=json"
        ),
        "title": "华通电脑2026年7月24日PE、PB与股息率",
        "publisher": "台湾证券交易所",
        "publish_date": "2026-07-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_twse",
        "is_primary_source": True,
        "source_credibility": "official_exchange_api",
        "independence_key": "twse_2313_20260724",
        "independence_rationale": "交易所单证券官方估值接口。",
    },
    {
        "source_ref": "twse_compeq_price_20260724",
        "source_url": (
            "https://www.twse.com.tw/rwd/en/afterTrading/STOCK_DAY?"
            "date=20260724&stockNo=2313&response=json"
        ),
        "title": "华通电脑2026年7月24日交易与收盘价",
        "publisher": "台湾证券交易所",
        "publish_date": "2026-07-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_twse",
        "is_primary_source": True,
        "source_credibility": "official_exchange_api",
        "independence_key": "twse_2313_20260724",
        "independence_rationale": "与同日估值接口属于同一交易所证券快照证据组。",
    },
    {
        "source_ref": "twse_unimicron_20260724",
        "source_url": (
            "https://www.twse.com.tw/rwd/en/afterTrading/BWIBBU?"
            "date=20260724&stockNo=3037&response=json"
        ),
        "title": "欣兴电子2026年7月24日PE、PB与股息率",
        "publisher": "台湾证券交易所",
        "publish_date": "2026-07-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_twse",
        "is_primary_source": True,
        "source_credibility": "official_exchange_api",
        "independence_key": "twse_3037_20260724",
        "independence_rationale": "交易所单证券官方估值接口。",
    },
    {
        "source_ref": "twse_unimicron_price_20260724",
        "source_url": (
            "https://www.twse.com.tw/rwd/en/afterTrading/STOCK_DAY?"
            "date=20260724&stockNo=3037&response=json"
        ),
        "title": "欣兴电子2026年7月24日交易与收盘价",
        "publisher": "台湾证券交易所",
        "publish_date": "2026-07-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_twse",
        "is_primary_source": True,
        "source_credibility": "official_exchange_api",
        "independence_key": "twse_3037_20260724",
        "independence_rationale": "与同日估值接口属于同一交易所证券快照证据组。",
    },
    {
        "source_ref": "twse_tripod_20260724",
        "source_url": (
            "https://www.twse.com.tw/rwd/en/afterTrading/BWIBBU?"
            "date=20260724&stockNo=3044&response=json"
        ),
        "title": "健鼎科技2026年7月24日PE、PB与股息率",
        "publisher": "台湾证券交易所",
        "publish_date": "2026-07-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_twse",
        "is_primary_source": True,
        "source_credibility": "official_exchange_api",
        "independence_key": "twse_3044_20260724",
        "independence_rationale": "交易所单证券官方估值接口。",
    },
    {
        "source_ref": "twse_tripod_price_20260724",
        "source_url": (
            "https://www.twse.com.tw/rwd/en/afterTrading/STOCK_DAY?"
            "date=20260724&stockNo=3044&response=json"
        ),
        "title": "健鼎科技2026年7月24日交易与收盘价",
        "publisher": "台湾证券交易所",
        "publish_date": "2026-07-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_twse",
        "is_primary_source": True,
        "source_credibility": "official_exchange_api",
        "independence_key": "twse_3044_20260724",
        "independence_rationale": "与同日估值接口属于同一交易所证券快照证据组。",
    },
    {
        "source_ref": "twse_zdt_20260724",
        "source_url": (
            "https://www.twse.com.tw/rwd/en/afterTrading/BWIBBU?"
            "date=20260724&stockNo=4958&response=json"
        ),
        "title": "臻鼎科技2026年7月24日PE、PB与股息率",
        "publisher": "台湾证券交易所",
        "publish_date": "2026-07-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_twse",
        "is_primary_source": True,
        "source_credibility": "official_exchange_api",
        "independence_key": "twse_4958_20260724",
        "independence_rationale": "交易所单证券官方估值接口。",
    },
    {
        "source_ref": "twse_zdt_price_20260724",
        "source_url": (
            "https://www.twse.com.tw/rwd/en/afterTrading/STOCK_DAY?"
            "date=20260724&stockNo=4958&response=json"
        ),
        "title": "臻鼎科技2026年7月24日交易与收盘价",
        "publisher": "台湾证券交易所",
        "publish_date": "2026-07-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_twse",
        "is_primary_source": True,
        "source_credibility": "official_exchange_api",
        "independence_key": "twse_4958_20260724",
        "independence_rationale": "与同日估值接口属于同一交易所证券快照证据组。",
    },
    {
        "source_ref": "yfinance_compeq_20260726",
        "source_url": "https://finance.yahoo.com/quote/2313.TW/",
        "title": "华通电脑yfinance估值与财务窄字段快照",
        "publisher": "Yahoo Finance/yfinance",
        "publish_date": "2026-07-26",
        "source_type": "website_material",
        "quality_tier": 3,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_yfinance",
        "is_primary_source": False,
        "source_credibility": "third_party_market_data_snapshot",
        "independence_key": "yfinance_hdi_peer_20260726",
        "independence_rationale": "同轮第三方行情快照；经营事实优先使用公司公告和交易所数据。",
    },
    {
        "source_ref": "yfinance_unimicron_20260726",
        "source_url": "https://finance.yahoo.com/quote/3037.TW/",
        "title": "欣兴电子yfinance估值与财务窄字段快照",
        "publisher": "Yahoo Finance/yfinance",
        "publish_date": "2026-07-26",
        "source_type": "website_material",
        "quality_tier": 3,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_yfinance",
        "is_primary_source": False,
        "source_credibility": "third_party_market_data_snapshot",
        "independence_key": "yfinance_hdi_peer_20260726",
        "independence_rationale": "同轮第三方行情快照；经营事实优先使用公司公告和交易所数据。",
    },
    {
        "source_ref": "yfinance_tripod_20260726",
        "source_url": "https://finance.yahoo.com/quote/3044.TW/",
        "title": "健鼎科技yfinance估值与财务窄字段快照",
        "publisher": "Yahoo Finance/yfinance",
        "publish_date": "2026-07-26",
        "source_type": "website_material",
        "quality_tier": 3,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_yfinance",
        "is_primary_source": False,
        "source_credibility": "third_party_market_data_snapshot",
        "independence_key": "yfinance_hdi_peer_20260726",
        "independence_rationale": "同轮第三方行情快照；经营事实优先使用公司公告和交易所数据。",
    },
    {
        "source_ref": "yfinance_zdt_20260726",
        "source_url": "https://finance.yahoo.com/quote/4958.TW/",
        "title": "臻鼎科技yfinance估值与财务窄字段快照",
        "publisher": "Yahoo Finance/yfinance",
        "publish_date": "2026-07-26",
        "source_type": "website_material",
        "quality_tier": 3,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_yfinance",
        "is_primary_source": False,
        "source_credibility": "third_party_market_data_snapshot",
        "independence_key": "yfinance_hdi_peer_20260726",
        "independence_rationale": "同轮第三方行情快照；经营事实优先使用公司公告和交易所数据。",
    },
    {
        "source_ref": "yfinance_ttm_20260726",
        "source_url": "https://finance.yahoo.com/quote/TTMI/",
        "title": "TTM Technologies yfinance估值与财务窄字段快照",
        "publisher": "Yahoo Finance/yfinance",
        "publish_date": "2026-07-26",
        "source_type": "website_material",
        "quality_tier": 3,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_yfinance",
        "is_primary_source": False,
        "source_credibility": "third_party_market_data_snapshot",
        "independence_key": "yfinance_hdi_peer_20260726",
        "independence_rationale": "同轮第三方行情快照；经营事实优先使用公司公告和交易所数据。",
    },
    {
        "source_ref": "yfinance_ats_20260726",
        "source_url": "https://finance.yahoo.com/quote/ATS.VI/",
        "title": "AT&S yfinance估值与财务窄字段快照",
        "publisher": "Yahoo Finance/yfinance",
        "publish_date": "2026-07-26",
        "source_type": "website_material",
        "quality_tier": 3,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "api_yfinance",
        "is_primary_source": False,
        "source_credibility": "third_party_market_data_snapshot",
        "independence_key": "yfinance_hdi_peer_20260726",
        "independence_rationale": "同轮第三方行情快照；经营事实优先使用公司公告和交易所数据。",
    },
]


GLOBAL_HDI_MARKET = {
    2024: (125.18, False),
    2025: (157.69, True),
    2026: (180.55, True),
    2030: (244.90, True),
}

HDI_2030_REGION = {
    "美洲": (5.91, 5.4),
    "欧洲": (3.10, 6.6),
    "日本": (5.62, 5.2),
    "中国大陆": (161.26, 9.1),
    "亚洲其他地区": (69.02, 10.3),
}

HDI_2024_APPLICATION = {
    "通信": 66.25,
    "其中：手机": 56.74,
    "消费电子": 15.85,
    "计算机": 14.19,
    "服务器": 12.84,
    "汽车": 10.69,
    "其他": 5.36,
}

GLOBAL_HDI_SHARE_2023 = [
    ("华通电脑", 10.0),
    ("AT&S", 7.7),
    ("TTM Technologies", 6.7),
    ("欣兴电子", 6.6),
    ("健鼎科技", 6.2),
    ("名幸电子", 6.2),
    ("臻鼎科技", 5.5),
]

CHINA_HDI_SHARE_2024 = [
    ("沪电股份", 8.0),
    ("汕头超声", 2.8),
    ("方正科技", 2.4),
    ("建滔集团", 2.2),
    ("胜宏科技", 2.1),
    ("红板科技", 2.1),
    ("超颖电子", 1.9),
    ("安捷利美维（厦门）", 1.6),
    ("名幸电子（武汉）", 1.0),
    ("中京电子", 1.0),
]

AI_PCB_TAM_USD_MN = {
    "AI服务器PCB合计": {2024: 3146, 2025: 4706, 2026: 10017, 2027: 27122},
    "GPU服务器PCB": {2024: 1407, 2025: 2242, 2026: 4493, 2027: 15887},
    "OAM": {2024: 522, 2025: 961, 2026: 2068, 2027: 6671},
    "UBB": {2024: 495, 2025: 552, 2026: 626, 2027: 642},
    "主板": {2024: 199, 2025: 207, 2026: 223, 2027: 196},
    "中板": {2024: 0, 2025: 0, 2026: 92, 2027: 1233},
    "背板": {2024: 0, 2025: 0, 2026: 0, 2027: 1941},
    "交换机板": {2024: 190, 2025: 442, 2026: 1243, 2027: 4955},
}

COMPANY_SPECS: list[dict[str, Any]] = [
    {
        "company_id": 589,
        "name": "华通电脑",
        "role": "全球HDI龙头",
        "global_share": 10.0,
        "global_rank": 1,
        "source_ref": "compeq_ar2024",
        "source_refs": [
            "compeq_ar2024",
            "twse_compeq_20260724",
            "twse_compeq_price_20260724",
            "yfinance_compeq_20260726",
        ],
        "products": "HDI、高层HDI、HLC、FPC、Rigid-Flex",
        "tech": "手机HDI基本盘深厚，向AI服务器、高速网络和光模块所需高层HDI/HLC迁移。",
        "recent": "公司年报把AI服务器、高速网络、光模块和卫星通信列为重点成长方向。",
        "risk": "手机需求波动、AI产品认证与高端产能爬坡可能使总HDI份额和AI份额走势分化。",
        "summary": "全球份额第一，但投资判断应区分成熟手机HDI与新兴AI高层HDI的利润结构。",
    },
    {
        "company_id": 218,
        "name": "AT&S",
        "role": "全球HDI龙头",
        "global_share": 7.7,
        "global_rank": 2,
        "source_ref": "ats_ar2025_26",
        "source_refs": ["ats_ar2025_26", "ats_fy2025_26_results", "yfinance_ats_20260726"],
        "products": "高端HDI、IC载板、汽车与工业高可靠PCB",
        "tech": "HDI和载板工艺积累深、专利密度高，具备欧洲与亚洲制造布局。",
        "recent": (
            "2025/26财年收入17.91亿欧元、EBITDA率23.3%；公司预计2026/27财年"
            "收入增长30%—35%、EBITDA率25%—29%，资本开支约4亿欧元。"
        ),
        "risk": "载板重资产扩张、产能利用率与欧洲成本结构可能压低短期回报。",
        "summary": "技术和专利壁垒突出，但财务回报同时受载板周期与资本开支影响。",
    },
    {
        "company_id": 562,
        "name": "TTM Technologies",
        "role": "全球HDI龙头",
        "global_share": 6.7,
        "global_rank": 3,
        "source_ref": "ttm_10k_2025",
        "source_refs": ["ttm_10k_2025", "ttm_q1_2026", "yfinance_ttm_20260726"],
        "products": "HDI、Ultra-HDI、HLC、RF、航天国防与系统集成",
        "tech": "监管年报定义先进HDI为多层微盲孔互连，量产30层以上并具备70层复杂板能力。",
        "recent": (
            "2026Q1收入8.46亿美元、同比增长30%，数据中心与网络占36%；"
            "纽约Syracuse Ultra-HDI项目预计2026年开始低速率生产。"
        ),
        "risk": "其优势横跨国防和高混合低批量，不能直接映射为AI服务器大批量份额。",
        "summary": "北美高可靠与Ultra-HDI战略价值高，和亚洲消费电子HDI厂商的商业模式不同。",
    },
    {
        "company_id": 467,
        "name": "欣兴电子",
        "role": "全球HDI龙头",
        "global_share": 6.6,
        "global_rank": 4,
        "source_ref": "redboard_sse_reply",
        "source_refs": [
            "redboard_sse_reply",
            "twse_unimicron_20260724",
            "twse_unimicron_price_20260724",
            "yfinance_unimicron_20260726",
        ],
        "products": "HDI、HLC、ABF/BT载板",
        "tech": "具备HDI与载板协同能力，AI产品同时受益于板级互连和封装升级。",
        "recent": "本地近期研报将AI载板和AI HDI列为2026年主要成长动能。",
        "risk": "载板景气与HDI景气会叠加财务波动，需分部观察而非用集团收入代替HDI收入。",
        "summary": "产品组合完整，核心看AI HDI与载板的稼动率和价格能否同步改善。",
    },
    {
        "company_id": 563,
        "name": "健鼎科技",
        "role": "全球HDI龙头",
        "global_share": 6.2,
        "global_rank": 5,
        "source_ref": "redboard_sse_reply",
        "source_refs": [
            "redboard_sse_reply",
            "twse_tripod_20260724",
            "twse_tripod_price_20260724",
            "yfinance_tripod_20260726",
        ],
        "products": "多层板、HDI、服务器/存储与汽车PCB",
        "tech": "具备多阶盲孔、Skip Via和高层HDI开发能力。",
        "recent": "持续面向服务器、存储、光模块和汽车场景开发高密度产品。",
        "risk": "不同应用的层数、材料和良率要求差异大，集团HDI份额不能代表AI高阶份额。",
        "summary": "规模和多场景客户结构较稳，但AI高阶HDI的独立收入仍需更多披露。",
    },
    {
        "company_id": 593,
        "name": "名幸电子",
        "role": "全球HDI龙头",
        "global_share": 6.2,
        "global_rank": 6,
        "source_ref": "meiko_ar2025",
        "source_refs": ["meiko_ar2025"],
        "products": "HDI、HLC、汽车、通信和存储PCB",
        "tech": "越南新厂面向中高层、高密度HDI，兼具汽车和通信产品经验。",
        "recent": "2025公司资料显示HDI销售从622亿日元增至887亿日元，并预计继续增长。",
        "risk": "汽车周期、汇率和新厂认证会影响收入兑现速度。",
        "summary": "是少数公开HDI产品收入的海外厂商，越南扩产提供全球交付增量。",
    },
    {
        "company_id": 561,
        "name": "臻鼎科技",
        "role": "全球HDI龙头",
        "global_share": 5.5,
        "global_rank": 7,
        "source_ref": "zdt_ar2025",
        "source_refs": [
            "zdt_ar2025",
            "zdt_huaian_investment",
            "twse_zdt_20260724",
            "twse_zdt_price_20260724",
            "yfinance_zdt_20260726",
        ],
        "products": "HDI、iHDI、HLC、FPC、SLP与IC载板",
        "tech": "产品谱系最完整之一，可从消费电子HDI迁移到AI服务器iHDI/HLC。",
        "recent": "2025—2028年淮安计划投入80亿元扩充MSAP、HDI和HLC高端产能。",
        "risk": "大额扩产需要客户认证和稼动率配合，消费电子基本盘仍带来季节性。",
        "summary": "全品类和规模优势明显，AI高端产能兑现是未来份额上行的关键。",
    },
    {
        "company_id": 555,
        "name": "胜宏科技",
        "role": "中国AI高阶HDI核心厂商",
        "china_share": 2.1,
        "china_rank": 5,
        "source_ref": "victory_ar2025",
        "products": "高阶HDI、HLC、GPU/OAM/UBB/交换机板、FPC",
        "tech": "已量产6阶24层HDI，具备10阶30层和16层Any-layer能力，研发14阶36层。",
        "recent": "2025收入和利润大幅增长，2026Q1延续增长，泰国A2计划2026Q3量产。",
        "risk": "客户集中、平台延期、认证/良率和资本开支强度会显著放大盈利波动。",
        "summary": "当前AI高阶HDI弹性最强，但市场估值已要求持续快速爬坡，需用利润和现金流双验证。",
    },
    {
        "company_id": 556,
        "name": "鹏鼎控股",
        "role": "消费电子HDI龙头与AI新进入者",
        "source_ref": "pengding_ar2025",
        "products": "FPC、SLP、IHDI、HLC、光模块与服务器PCB",
        "tech": "mSAP/SLP量产经验可迁移到高阶IHDI和光模块PCB。",
        "recent": "淮安IHDI/HLC产能预计2026年底翻倍，泰国一厂试产，多期项目推进。",
        "risk": "AI收入占比仍小于消费电子基本盘，扩产折旧可能先于收入。",
        "summary": "技术迁移路径清晰，但当前估值对AI新业务的收入和利润率要求很高。",
    },
    {
        "company_id": 558,
        "name": "景旺电子",
        "role": "综合PCB厂商与HDI扩产者",
        "source_ref": "kinwong_ar2025",
        "products": "HDI（含SLP）、HLC、FPC、汽车与工业PCB",
        "tech": "珠海规划60万平方米HDI/SLP和120万平方米HLC，部分产线投产。",
        "recent": "泰国基地计划2026年投产；2026Q1收入增长但利润下滑。",
        "risk": "产能爬坡、折旧和产品结构使利润恢复可能慢于收入增长。",
        "summary": "增长基础广，但AI高阶产品要先验证利润率而不是只看产能面积。",
    },
    {
        "company_id": 633,
        "name": "红板科技",
        "role": "中国HDI成长厂商",
        "china_share": 2.1,
        "china_rank": 6,
        "source_ref": "redboard_sse_reply",
        "products": "HDI、高频高速板、多层板",
        "tech": "中高端HDI收入占比提升，份额仍明显低于全球头部。",
        "recent": "2026年4月上市；2025年收入和净利润继续增长。",
        "risk": "上市历史短、当前估值高，客户、阶数与新增产能披露不足以支撑精确远期份额。",
        "summary": "成长性较好，但需要用订单、阶数和现金流验证高估值，而不能只按国产替代叙事外推。",
    },
    {
        "company_id": 326,
        "name": "沪电股份",
        "role": "中国大陆HDI份额第一与HLC边界公司",
        "china_share": 8.0,
        "china_rank": 1,
        "source_ref": "wus_ar2025",
        "products": "高多层、高速网络、服务器与部分HDI",
        "tech": "数通HLC优势强，研究时必须把高多层板和严格HDI分开。",
        "recent": "2025盈利继续增长，高速网络和AI服务器需求强。",
        "risk": "中国HDI份额统计不等于AI高阶HDI份额，HLC收入不可机械并入HDI。",
        "summary": "是国内高端PCB核心公司，但HDI研究需保留产品边界，避免把HLC优势重复计入。",
    },
    {
        "company_id": 472,
        "name": "深南电路",
        "role": "高端PCB与载板综合龙头",
        "source_ref": "shennan_ar2025",
        "products": "HLC、部分HDI、封装基板、电子装联",
        "tech": "高层高速板、背板与载板能力强，严格HDI并非全部AI PCB产品。",
        "recent": "2025年报引用Prismark最新产品市场预测，AI PCB产能继续扩张。",
        "risk": "分部混合和载板扩产会使集团利润与HDI景气不同步。",
        "summary": "技术平台价值高，HDI专题中主要作为高端PCB边界和协同能力比较对象。",
    },
    {
        "company_id": 582,
        "name": "方正科技",
        "role": "中国高阶HDI厂商",
        "china_share": 2.4,
        "china_rank": 3,
        "source_ref": "redboard_sse_reply",
        "products": "高阶HDI与高多层PCB",
        "tech": "2024年披露的HDI产能以高阶产品为主。",
        "recent": "资本开支和产品结构升级推动收入与利润增长。",
        "risk": "扩产期折旧、客户认证与集团治理变化需要持续跟踪。",
        "summary": "国内份额居前，判断重点是高阶产能利用率和利润率持续性。",
    },
    {
        "company_id": 583,
        "name": "生益电子",
        "role": "服务器PCB与高阶HDI扩产者",
        "source_ref": "redboard_sse_reply",
        "products": "服务器HLC、高阶HDI、通信与汽车PCB",
        "tech": "设备投入强度较高，产品技术复杂度高于普通HDI。",
        "recent": "AI服务器需求改善带动高端产品结构升级。",
        "risk": "与母公司生益科技的材料业务需区分，PCB产能爬坡影响短期利润。",
        "summary": "具备服务器客户和材料协同，但需分别验证HLC与HDI收入。",
    },
]


def _point(
    source_ref: str,
    metric: str,
    period: str,
    unit: str,
    excerpt: str,
    *,
    value_num: float | None = None,
    value_text: str | None = None,
    forecast: bool = False,
    method: str = "pdf_direct",
    note: str = "",
    scope_key: str = "industry",
    company: str | None = None,
) -> dict[str, Any]:
    return {
        "source_ref": source_ref,
        "metric": metric,
        "period": period,
        "unit": unit,
        "value_num": value_num,
        "value_text": value_text,
        "source_excerpt": excerpt,
        "extraction_method": method,
        "is_forecast": forecast,
        "note": note,
        "scope_key": scope_key,
        **({"company": company} if company else {}),
    }


def build_data_points() -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    prismark_excerpt = (
        "Prismark 2025Q4产品预测：HDI 2024年125.18亿美元，2025年157.69亿美元，"
        "2026年180.55亿美元，2030年244.90亿美元；2025—2030年复合增速9.2%。"
    )
    for year, (value, forecast) in GLOBAL_HDI_MARKET.items():
        points.append(
            _point(
                "shennan_ar2025",
                "全球HDI市场规模",
                f"{year}{'E' if forecast else ''}",
                "亿美元",
                prismark_excerpt,
                value_num=value,
                forecast=forecast,
                scope_key="global_hdi_market",
            )
        )
    points.append(
        _point(
            "shennan_ar2025",
            "全球HDI市场2025—2030年复合增速",
            "2025E-2030E",
            "%",
            prismark_excerpt,
            value_num=9.2,
            forecast=True,
            scope_key="global_hdi_market",
        )
    )
    points.append(
        _point(
            "shennan_ar2025",
            "全球HDI市场2024—2030年隐含复合增速",
            "2024-2030E",
            "%",
            prismark_excerpt,
            value_num=11.82,
            forecast=True,
            method="inferred",
            note="计算公式=(244.90/125.18)^(1/6)-1。",
            scope_key="global_hdi_market",
        )
    )
    region_excerpt = (
        "Prismark 2025Q4区域表显示2030年HDI产值：美洲5.91、欧洲3.10、日本5.62、"
        "中国161.26、亚洲其他69.02亿美元，合计约244.91亿美元。"
    )
    for region, (value, cagr) in HDI_2030_REGION.items():
        points.append(
            _point(
                "wus_ar2025",
                f"2030年HDI产值-{region}",
                "2030E",
                "亿美元",
                region_excerpt,
                value_num=value,
                forecast=True,
                scope_key="hdi_region_2030",
            )
        )
        points.append(
            _point(
                "wus_ar2025",
                f"HDI产值2025—2030年复合增速-{region}",
                "2025E-2030E",
                "%",
                region_excerpt,
                value_num=cagr,
                forecast=True,
                scope_key="hdi_region_growth",
            )
        )
    points.append(
        _point(
            "wus_ar2025",
            "2030年中国大陆HDI产值占全球比重",
            "2030E",
            "%",
            region_excerpt,
            value_num=65.85,
            forecast=True,
            method="inferred",
            note="计算公式=161.26/244.90。",
            scope_key="hdi_region_2030",
        )
    )
    app_excerpt = (
        "2024年全球HDI按应用拆分：通信66.25亿美元，其中手机56.74亿美元；"
        "消费15.85、计算机14.19、服务器12.84、汽车10.69、其他5.36亿美元。"
    )
    for application, value in HDI_2024_APPLICATION.items():
        points.append(
            _point(
                "redboard_sse_reply",
                f"全球HDI市场规模-{application}",
                "2024",
                "亿美元",
                app_excerpt,
                value_num=value,
                scope_key="hdi_application_2024",
            )
        )
    points.append(
        _point(
            "redboard_sse_reply",
            "服务器占全球HDI市场比重",
            "2024",
            "%",
            app_excerpt,
            value_num=10.26,
            method="inferred",
            note="计算公式=12.84/125.18。",
            scope_key="hdi_application_2024",
        )
    )
    share_excerpt = (
        "问询回复引用Prismark列示2023年全球HDI前七家：华通10.0%、AT&S 7.7%、"
        "TTM 6.7%、欣兴6.6%、健鼎6.2%、名幸6.2%、臻鼎5.5%。"
    )
    for rank, (company, share) in enumerate(GLOBAL_HDI_SHARE_2023, start=1):
        points.append(
            _point(
                "redboard_sse_reply",
                f"全球HDI市场份额-{company}",
                "2023",
                "%",
                share_excerpt,
                value_num=share,
                scope_key="global_hdi_share_2023",
                company=company,
            )
        )
        points.append(
            _point(
                "redboard_sse_reply",
                f"全球HDI份额排名-{company}",
                "2023",
                "名",
                share_excerpt,
                value_num=rank,
                scope_key="global_hdi_share_2023",
                company=company,
            )
        )
    for label, count in (("CR3", 3), ("CR5", 5), ("CR7", 7)):
        value = round(sum(share for _, share in GLOBAL_HDI_SHARE_2023[:count]), 1)
        points.append(
            _point(
                "redboard_sse_reply",
                f"全球HDI市场集中度-{label}",
                "2023",
                "%",
                share_excerpt,
                value_num=value,
                method="inferred",
                note=f"计算公式=全球份额表前{count}家份额求和。",
                scope_key="global_hdi_concentration",
            )
        )
    china_excerpt = (
        "问询回复引用CPCA/Prismark列示2024年中国大陆HDI前十家份额，沪电8.0%居首，"
        "前十家合计25.1%。"
    )
    for rank, (company, share) in enumerate(CHINA_HDI_SHARE_2024, start=1):
        points.append(
            _point(
                "redboard_sse_reply",
                f"中国大陆HDI市场份额-{company}",
                "2024",
                "%",
                china_excerpt,
                value_num=share,
                scope_key="china_hdi_share_2024",
            )
        )
    for label, count in (("CR3", 3), ("CR5", 5), ("CR10", 10)):
        value = round(sum(share for _, share in CHINA_HDI_SHARE_2024[:count]), 1)
        points.append(
            _point(
                "redboard_sse_reply",
                f"中国大陆HDI市场集中度-{label}",
                "2024",
                "%",
                china_excerpt,
                value_num=value,
                method="inferred",
                note=f"计算公式=中国大陆份额表前{count}家份额求和。",
                scope_key="china_hdi_concentration",
            )
        )
    points.extend(
        [
            _point(
                "redboard_sse_reply",
                "中国大陆HDI产值",
                "2024",
                "亿美元",
                "2024年中国大陆HDI产值78.49亿美元，占全球约62.7%。",
                value_num=78.49,
                scope_key="china_hdi_market",
            ),
            _point(
                "redboard_sse_reply",
                "中国大陆HDI产值占全球比重",
                "2024",
                "%",
                "2024年中国大陆HDI产值78.49亿美元，占全球约62.7%。",
                value_num=62.70,
                method="inferred",
                note="计算公式=78.49/125.18。",
                scope_key="china_hdi_market",
            ),
        ]
    )
    fs_excerpt = (
        "受聘行业顾问口径：2024年全球HDI约128亿美元，其中低Build-up 68亿美元、"
        "高Build-up 60亿美元；2029年全球HDI约169亿美元。"
    )
    for metric, value, period in (
        ("全球HDI市场规模-较早预测口径", 128.0, "2024"),
        ("全球低Build-up HDI市场规模", 68.0, "2024"),
        ("全球高Build-up HDI市场规模", 60.0, "2024"),
        ("全球HDI市场规模-较早预测口径", 169.0, "2029E"),
        ("高Build-up HDI市场规模-AI/HPC", 13.0, "2024"),
        ("高Build-up HDI市场规模-通信", 7.0, "2024"),
        ("高Build-up HDI市场规模-智能设备", 29.0, "2024"),
        ("高Build-up HDI市场规模-汽车", 6.0, "2024"),
        ("高Build-up HDI市场规模-AI/HPC", 32.0, "2029E"),
    ):
        points.append(
            _point(
                "victory_h_prospectus",
                metric,
                period,
                "亿美元",
                fs_excerpt,
                value_num=value,
                forecast=period.endswith("E"),
                scope_key="hdi_forecast_vintage",
            )
        )
    points.append(
        _point(
            "victory_h_prospectus",
            "高Build-up HDI-AI/HPC市场2025—2029年复合增速",
            "2025E-2029E",
            "%",
            "招股文件预计高Build-up HDI的AI/HPC应用2029年达到32亿美元，2025—2029年复合增速13.7%。",
            value_num=13.7,
            forecast=True,
            scope_key="hdi_forecast_vintage",
        )
    )
    ai_excerpt = (
        "Goldman Sachs自建AI PCB TAM按节点拆分GPU服务器、OAM、UBB、主板、"
        "中板、背板和交换机板；这是AI PCB总盘，不等于严格HDI。"
    )
    for category, series in AI_PCB_TAM_USD_MN.items():
        for year, value in series.items():
            points.append(
                _point(
                    "gs_ai_pcb_tam",
                    f"AI PCB市场规模-{category}",
                    f"{year}{'E' if year >= 2025 else ''}",
                    "百万美元",
                    ai_excerpt,
                    value_num=value,
                    forecast=year >= 2025,
                    scope_key="ai_pcb_tam_not_strict_hdi",
                )
            )
    points.extend(
        [
            _point(
                "ipc_4104",
                "IPC微盲孔直径上限",
                "IPC/JPCA-4104",
                "毫米",
                "IPC/JPCA-4104将微盲孔描述为直径不超过0.15毫米、焊盘直径不超过0.35毫米。",
                value_num=0.15,
                method="web_fetch",
                scope_key="hdi_definition",
            ),
            _point(
                "ipc_4104",
                "IPC微盲孔焊盘直径上限",
                "IPC/JPCA-4104",
                "毫米",
                "IPC/JPCA-4104将微盲孔描述为直径不超过0.15毫米、焊盘直径不超过0.35毫米。",
                value_num=0.35,
                method="web_fetch",
                scope_key="hdi_definition",
            ),
            _point(
                "ipc_4104",
                "IPC新增HDI介质层厚度上限",
                "IPC/JPCA-4104",
                "毫米",
                "IPC/JPCA-4104覆盖新增HDI层厚度不超过0.15毫米的材料。",
                value_num=0.15,
                method="web_fetch",
                scope_key="hdi_definition",
            ),
            _point(
                "ttm_10k_2025",
                "TTM HDI细线路线宽/线距上限",
                "2025",
                "毫米",
                "TTM 10-K将HDI描述为微盲孔不超过0.15毫米、线宽线距不超过0.075毫米。",
                value_num=0.075,
                method="web_fetch",
                scope_key="hdi_definition",
                company="TTM Technologies",
            ),
            _point(
                "ttm_10k_2025",
                "TTM SLP细线路宽/线距上限",
                "2025",
                "毫米",
                "TTM 10-K将SLP描述为线宽线距不超过0.02毫米的更高密度路线。",
                value_num=0.02,
                method="web_fetch",
                scope_key="hdi_definition",
                company="TTM Technologies",
            ),
            _point(
                "ttm_10k_2025",
                "TTM先进HDI定义",
                "2025",
                "定义",
                "TTM把先进HDI定义为具有一层以上微盲孔互连结构的产品。",
                value_text="一层以上微盲孔互连结构",
                method="web_fetch",
                scope_key="hdi_definition",
                company="TTM Technologies",
            ),
            _point(
                "ttm_hdi_product",
                "TTM激光微盲孔最小钻孔直径",
                "2026",
                "微米",
                "TTM产品页披露激光微盲孔钻孔直径可小至100微米，焊盘可小至200微米。",
                value_num=100,
                method="web_fetch",
                scope_key="hdi_technology",
                company="TTM Technologies",
            ),
            _point(
                "ttm_hdi_product",
                "TTM激光微盲孔最小焊盘直径",
                "2026",
                "微米",
                "TTM产品页披露激光微盲孔钻孔直径可小至100微米，焊盘可小至200微米。",
                value_num=200,
                method="web_fetch",
                scope_key="hdi_technology",
                company="TTM Technologies",
            ),
            _point(
                "ipc_microvia_warning",
                "高性能产品微盲孔潜在失效风险",
                "2019",
                "风险事实",
                "IPC警告部分微盲孔失效在裸板验收时不可见，可能在回流焊、整机筛选或服役阶段出现。",
                value_text="传统切片和目检可能漏检潜在微盲孔失效",
                method="web_fetch",
                scope_key="hdi_reliability",
            ),
        ]
    )
    company_facts = [
        ("victory_ar2025", "胜宏科技", "量产HDI阶数/层数", "2025", "阶/层", "6阶24层", "公司披露已大规模量产6阶24层HDI。"),
        ("victory_ar2025", "胜宏科技", "HDI技术能力", "2025", "阶/层", "10阶30层", "公司披露具备10阶30层HDI技术能力。"),
        ("victory_ar2025", "胜宏科技", "Any-layer HDI能力", "2025", "层", "16层", "公司披露具备16层任意互联HDI能力。"),
        ("victory_ar2025", "胜宏科技", "下一代HDI研发目标", "2025", "阶/层", "14阶36层", "公司推进14阶36层HDI研发认证。"),
        ("victory_q1_2026", "胜宏科技", "季度营业收入", "2026Q1", "亿元人民币", 55.19, "2026Q1收入55.19亿元，同比增长27.99%。"),
        ("victory_q1_2026", "胜宏科技", "季度归母净利润", "2026Q1", "亿元人民币", 12.88, "2026Q1归母净利12.88亿元，同比增长39.95%。"),
        ("victory_q1_2026", "胜宏科技", "在建工程", "2026Q1", "亿元人民币", 51.70, "2026Q1期末在建工程51.70亿元，同比期初增加43.21%。"),
        ("victory_h_prospectus", "胜宏科技", "HDI平均售价", "2024", "元/平方米", 2351, "招股文件披露2024年HDI平均售价2351元/平方米。"),
        ("victory_h_prospectus", "胜宏科技", "HDI平均售价", "2025", "元/平方米", 13475, "招股文件披露2025年HDI平均售价13475元/平方米，主要因高端产品占比提升。"),
        ("victory_h_prospectus", "胜宏科技", "HDI毛利率", "2024", "%", 22.5, "招股文件披露2024年HDI毛利率22.5%。"),
        ("victory_h_prospectus", "胜宏科技", "HDI毛利率", "2025", "%", 43.5, "招股文件披露2025年HDI毛利率43.5%。"),
        ("pengding_q1_2026", "鹏鼎控股", "季度营业收入", "2026Q1", "亿元人民币", 79.86, "2026Q1收入79.86亿元，同比下降1.25%。"),
        ("pengding_q1_2026", "鹏鼎控股", "季度归母净利润", "2026Q1", "亿元人民币", 4.63, "2026Q1归母净利4.63亿元，同比下降5.21%。"),
        ("pengding_ar2025", "鹏鼎控股", "淮安PCB产业园计划投资", "2025-2028", "亿元人民币", 80, "公司计划2025年下半年至2028年在淮安投入80亿元建设PCB产业园。"),
        ("pengding_ar2025", "鹏鼎控股", "淮安高端PCB项目计划投资", "未来", "亿元人民币", 110, "公司2026年初签署协议，拟投资110亿元建设高端PCB基地。"),
        ("pengding_ar2025", "鹏鼎控股", "淮安IHDI/HLC产能变化目标", "2026E", "倍", 2.0, "公司预计至2026年底淮安IHDI与HLC产能翻倍。"),
        ("kinwong_q1_2026", "景旺电子", "季度营业收入", "2026Q1", "亿元人民币", 38.92, "2026Q1收入38.92亿元，同比增长16.41%。"),
        ("kinwong_q1_2026", "景旺电子", "季度归母净利润", "2026Q1", "亿元人民币", 2.33, "2026Q1归母净利2.33亿元，同比下降28.37%。"),
        ("kinwong_ar2025", "景旺电子", "珠海HDI含SLP规划年产能", "规划", "万平方米/年", 60, "珠海一期规划年产60万平方米HDI（含SLP）。"),
        ("kinwong_ar2025", "景旺电子", "珠海HLC规划年产能", "规划", "万平方米/年", 120, "珠海一期规划年产120万平方米HLC。"),
        ("meiko_ar2025", "名幸电子", "HDI销售额", "FY2023", "十亿日元", 62.2, "Meiko资料披露FY2023 HDI销售额622亿日元。"),
        ("meiko_ar2025", "名幸电子", "HDI销售额", "FY2024", "十亿日元", 88.7, "Meiko资料披露FY2024 HDI销售额887亿日元。"),
        ("meiko_ar2025", "名幸电子", "HDI销售额预测", "FY2025E", "十亿日元", 94.0, "Meiko预计FY2025 HDI销售额940亿日元。"),
        ("zdt_huaian_investment", "臻鼎科技", "淮安高阶PCB计划投资", "2025H2-2028", "亿元人民币", 80, "臻鼎公告淮安园区计划投入80亿元扩充MSAP、HDI、HLC产能。"),
        ("ttm_10k_2025", "TTM Technologies", "Syracuse Ultra-HDI一期投资区间下限", "规划", "百万美元", 100, "TTM 10-K披露Syracuse一期投资预计1.00亿至1.30亿美元。"),
        ("ttm_10k_2025", "TTM Technologies", "Syracuse Ultra-HDI一期投资区间上限", "规划", "百万美元", 130, "TTM 10-K披露Syracuse一期投资预计1.00亿至1.30亿美元。"),
        ("ats_patent_quality", "AT&S", "已授权知识产权数量", "2025", "项", 1700, "AT&S称拥有超过1700项授权保护权利。"),
    ]
    for source_ref, company, metric, period, unit, value, excerpt in company_facts:
        if isinstance(value, (int, float)):
            points.append(
                _point(
                    source_ref,
                    metric,
                    period,
                    unit,
                    excerpt,
                    value_num=float(value),
                    forecast="E" in period or period in {"规划", "未来"},
                    method="web_fetch" if source_ref in {"zdt_huaian_investment", "ttm_10k_2025", "ats_patent_quality"} else "pdf_direct",
                    scope_key=f"company_{company}",
                    company=company,
                )
            )
        else:
            points.append(
                _point(
                    source_ref,
                    metric,
                    period,
                    unit,
                    excerpt,
                    value_text=str(value),
                    scope_key=f"company_{company}",
                    company=company,
                )
            )
    top100_excerpt = (
        "Prismark公开摘要称2024年Top100企业合计收入745亿美元，其中约115亿美元为"
        "组装或非PCB收入；裸板收入约631亿美元，占全球裸板产值约86%。"
    )
    for metric, value, unit in (
        ("全球PCB Top100合计收入", 745, "亿美元"),
        ("全球PCB Top100非裸板及组装收入", 115, "亿美元"),
        ("全球PCB Top100裸板收入", 631, "亿美元"),
        ("全球PCB Top100裸板收入占全球比重", 86, "%"),
    ):
        points.append(
            _point(
                "prismark_top100_2024",
                metric,
                "2024",
                unit,
                top100_excerpt,
                value_num=value,
                method="web_fetch",
                scope_key="pcb_context_not_hdi_share",
            )
        )
    return points


KEY_ARGUMENTS = [
    {
        "source_ref": "redboard_sse_reply",
        "argument": "全球HDI前七家合计48.9%，但中国大陆前十家仅25.1%，全球高端能力集中与大陆生产地分散并存。",
        "sentiment": "中性",
        "dimension": "竞争格局",
    },
    {
        "source_ref": "shennan_ar2025",
        "argument": "Prismark 2025Q4把全球HDI 2025—2030年复合增速上修至9.2%，显著高于较早预测。",
        "sentiment": "看涨",
        "dimension": "市场空间",
    },
    {
        "source_ref": "victory_h_prospectus",
        "argument": "高Build-up HDI的AI/HPC细分增长快于传统手机HDI，但受聘顾问预测与最新Prismark存在明显口径和时间差。",
        "sentiment": "看涨",
        "dimension": "需求结构",
    },
    {
        "source_ref": "ipc_microvia_warning",
        "argument": "高阶HDI的核心壁垒不是名义层数，而是多次压合、电镀填孔、对准、热循环可靠性和批量良率。",
        "sentiment": "中性",
        "dimension": "技术壁垒",
    },
    {
        "source_ref": "pengding_ar2025",
        "argument": "大额IHDI/HLC扩产创造收入选择权，也会在认证和稼动率不足时形成折旧与自由现金流压力。",
        "sentiment": "中性",
        "dimension": "供给与财务",
    },
]
