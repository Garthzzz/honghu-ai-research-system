from __future__ import annotations

"""铜行业 B 轨研究的来源登记、经营事实和可复算行业模型数据。

财务报表、市场估值、一致预期和公司内部预测不在这里复制；它们保存在
``financial.db``。本文件只承载行业供需、矿山经营、项目和政策事实。
"""

from typing import Any


SOURCE_SPECS: list[dict[str, Any]] = [
    {
        "source_ref": "icsg_factbook_2025",
        "source_file": "2025-10_ICSG_世界铜业事实手册2025_官方英文.pdf",
        "title": "ICSG《世界铜业事实手册2025》",
        "publisher": "International Copper Study Group",
        "publish_date": "2025-10-01",
        "source_type": "协会数据",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "international_industry_organization",
        "independence_key": "icsg_factbook_2025",
        "independence_rationale": "ICSG原始行业统计手册；与ICSG月报和预测属于同一机构但不同统计产品。",
    },
    {
        "source_ref": "icsg_forecast_20260423",
        "source_file": "2026-04-23_ICSG_铜市场2026至2027预测_官方英文.pdf",
        "title": "ICSG《2026—2027年铜市场预测》",
        "publisher": "International Copper Study Group",
        "publish_date": "2026-04-23",
        "source_type": "协会数据",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "international_industry_organization",
        "independence_key": "icsg_forecast_20260423",
        "independence_rationale": "ICSG春季预测，作为2025—2027年全球供需统一口径。",
    },
    {
        "source_ref": "icsg_july_regional_2026",
        "source_file": "2026-07_ICSG_分区域矿山冶炼精炼与消费表_官方英文.pdf",
        "title": "ICSG 2026年7月分区域矿山、冶炼、精炼与消费表",
        "publisher": "International Copper Study Group",
        "publish_date": "2026-07-01",
        "source_type": "协会数据",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "international_industry_organization",
        "independence_key": "icsg_july_2026_bulletin",
        "independence_rationale": "ICSG月度统计表；与同月全球表共享同一月报底稿。",
    },
    {
        "source_ref": "icsg_july_global_2026",
        "source_file": "2026-07_ICSG_全球精炼铜产量消费库存价格表_官方英文.pdf",
        "title": "ICSG 2026年7月全球精炼铜产量、消费、库存与价格表",
        "publisher": "International Copper Study Group",
        "publish_date": "2026-07-01",
        "source_type": "协会数据",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "international_industry_organization",
        "independence_key": "icsg_july_2026_bulletin",
        "independence_rationale": "ICSG月度统计表；与同月分区域表共享同一月报底稿。",
    },
    {
        "source_ref": "iea_gcm_2026",
        "source_file": "2026-07-16_IEA_全球关键矿产展望2026_官方英文.pdf",
        "title": "IEA《全球关键矿产展望2026》",
        "publisher": "International Energy Agency",
        "publish_date": "2026-07-16",
        "source_type": "协会数据",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "international_energy_organization",
        "independence_key": "iea_global_critical_minerals_outlook_2026",
        "independence_rationale": "IEA独立长期需求和项目供给模型。",
    },
    {
        "source_ref": "usgs_mcs_2026",
        "source_file": "2026-02_USGS_矿产品摘要2026_官方英文.pdf",
        "title": "USGS《矿产品摘要2026：铜》",
        "publisher": "U.S. Geological Survey",
        "publish_date": "2026-02-01",
        "source_type": "协会数据",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "government_statistics",
        "independence_key": "usgs_mcs_copper_2026",
        "independence_rationale": "美国地质调查局矿山产量、储量和美国供需原始统计。",
    },
    {
        "source_ref": "zijin_ar2025",
        "source_file": "2026-04-27_紫金矿业_2025年年度报告_官方英文.pdf",
        "title": "紫金矿业2025年年度报告",
        "publisher": "紫金矿业",
        "publish_date": "2026-04-27",
        "source_type": "公告",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "zijin_ar2025",
        "independence_rationale": "公司经审计年度报告。",
    },
    {
        "source_ref": "zijin_q1_2026",
        "source_file": "2026-04-27_紫金矿业_2026年第一季度报告_官方英文.pdf",
        "title": "紫金矿业2026年第一季度报告",
        "publisher": "紫金矿业",
        "publish_date": "2026-04-27",
        "source_type": "公告",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_filing",
        "independence_key": "zijin_q1_2026",
        "independence_rationale": "公司季度报告。",
    },
    {
        "source_ref": "cmoc_ar2025",
        "source_file": "2026-03-28_洛阳钼业_2025年年度报告_官方.pdf",
        "title": "洛阳钼业2025年年度报告",
        "publisher": "洛阳钼业",
        "publish_date": "2026-03-28",
        "source_type": "公告",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "cmoc_ar2025",
        "independence_rationale": "公司经审计年度报告。",
    },
    {
        "source_ref": "cmoc_q1_2026",
        "source_file": "2026-04-25_洛阳钼业_2026年第一季度报告_官方.pdf",
        "title": "洛阳钼业2026年第一季度报告",
        "publisher": "洛阳钼业",
        "publish_date": "2026-04-25",
        "source_type": "公告",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_filing",
        "independence_key": "cmoc_q1_2026",
        "independence_rationale": "公司季度报告。",
    },
    {
        "source_ref": "mmg_ar2025",
        "source_file": "2026-04-21_五矿资源_2025年年度报告_官方英文.pdf",
        "title": "五矿资源2025年年度报告",
        "publisher": "MMG Limited",
        "publish_date": "2026-04-21",
        "source_type": "公告",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "mmg_ar2025",
        "independence_rationale": "公司经审计年度报告。",
    },
    {
        "source_ref": "mmg_q1_2026",
        "source_file": "2026-04-21_五矿资源_2026年第一季度生产报告_官方英文.pdf",
        "title": "五矿资源2026年第一季度生产报告",
        "publisher": "MMG Limited",
        "publish_date": "2026-04-21",
        "source_type": "公告",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "mmg_q1_2026",
        "independence_rationale": "公司季度生产报告。",
    },
    {
        "source_ref": "mmg_q2_2026",
        "source_file": "2026-07-21_五矿资源_2026年第二季度生产报告_官方英文.pdf",
        "title": "五矿资源2026年第二季度生产报告",
        "publisher": "MMG Limited",
        "publish_date": "2026-07-21",
        "source_type": "公告",
        "quality_tier": 1,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "mmg_q2_2026",
        "independence_rationale": "公司季度生产报告。",
    },
    {
        "source_ref": "pacific_copper_20260705",
        "source_file": "2026-07-05_太平洋证券_有色金属_铜行业深度报告：供需呈现双强格局，铜价有望延续强势.pdf",
        "title": "铜行业深度：供需呈现双强格局，铜价有望延续强势",
        "publisher": "太平洋证券",
        "publish_date": "2026-07-05",
        "source_type": "卖方深度",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "sell_side_industry_model",
        "independence_key": "pacific_copper_20260705",
        "independence_rationale": "卖方供需模型；用于外部对账，不作为官方统计。",
    },
    {
        "source_ref": "orient_copper_20260721",
        "source_file": "2026-07-21_东方证券_有色金属_铜行业深度报告：预期走向现实，铜价蓄势待发.pdf",
        "title": "铜行业深度：预期走向现实，铜价蓄势待发",
        "publisher": "东方证券",
        "publish_date": "2026-07-21",
        "source_type": "卖方深度",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "sell_side_industry_model",
        "independence_key": "orient_copper_20260721",
        "independence_rationale": "卖方需求与项目模型；用于口径和结果对账。",
    },
    {
        "source_ref": "ivanhoe_kamoa_20260331",
        "source_url": "https://www.ivanhoemines.com/news-stories/news-release/ivanhoe-mines-announces-updated-independent-study-results-for-the-kamoa-kakula-copper-complex/",
        "title": "Kamoa-Kakula更新独立研究及2026—2027年指引",
        "publisher": "Ivanhoe Mines",
        "publish_date": "2026-03-31",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "project_operator_release",
        "independence_key": "ivanhoe_kamoa_20260331",
        "independence_rationale": "项目运营方原始指引和独立技术研究摘要。",
    },
    {
        "source_ref": "rio_oyu_20260630",
        "source_url": "https://www.riotinto.com/news/releases/2026/rio-tinto-and-government-of-mongolia-agree-to-adjust-oyu-tolgoi-shareholder-loan-interest-rate",
        "title": "Rio Tinto与蒙古政府调整Oyu Tolgoi股东贷款利率",
        "publisher": "Rio Tinto",
        "publish_date": "2026-06-30",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "project_operator_release",
        "independence_key": "rio_oyu_20260630",
        "independence_rationale": "项目运营方关于产量爬坡和政府协议的原始公告。",
    },
    {
        "source_ref": "fcx_grasberg_restart",
        "source_url": "https://investors.fcx.com/investors/news-releases/news-release-details/2025/Freeport-Provides-Update-on-Restart-Plans-for-Grasberg-Minerals-District/default.aspx",
        "title": "Freeport更新Grasberg分阶段恢复计划",
        "publisher": "Freeport-McMoRan",
        "publish_date": "2025-12-08",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "project_operator_release",
        "independence_key": "fcx_grasberg_restart_20251208",
        "independence_rationale": "项目运营方分阶段恢复和产量指引。",
    },
    {
        "source_ref": "bhp_escondida_20260317",
        "source_url": "https://www.bhp.com/news/articles/2026/03/escondida--bhp-submits-environmental-permit-to-build-a-new-concentrator-plant",
        "title": "Escondida提交新选厂环境许可",
        "publisher": "BHP",
        "publish_date": "2026-03-17",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "project_operator_release",
        "independence_key": "bhp_escondida_20260317",
        "independence_rationale": "项目运营方资本开支、产能和时间表公告。",
    },
    {
        "source_ref": "teck_qb_outlook",
        "source_url": "https://www.teck.com/news/news-releases/2025/teck-announces-completion-of-comprehensive-operational-review-and-updated-outlook",
        "title": "Teck完成运营复核并下调Quebrada Blanca指引",
        "publisher": "Teck Resources",
        "publish_date": "2025-10-23",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "project_operator_release",
        "independence_key": "teck_qb_review_20251023",
        "independence_rationale": "项目运营方经全面运营复核后的产量指引。",
    },
    {
        "source_ref": "antofagasta_cent_2026",
        "source_url": "https://www.antofagasta.co.uk/investors/news/2026/q2-2026-production-report/",
        "title": "Antofagasta 2026年第二季度生产报告",
        "publisher": "Antofagasta",
        "publish_date": "2026-07-22",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "antofagasta_q2_2026",
        "independence_rationale": "运营方关于Centinela第二选厂进度的季度报告。",
    },
    {
        "source_ref": "southern_tia_maria_20260624",
        "source_url": "https://southerncoppercorp.com/wp-content/uploads/2026/06/pr260624.pdf",
        "title": "Southern Peru完成Tía María项目融资",
        "publisher": "Southern Copper",
        "publish_date": "2026-06-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "es",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "project_operator_release",
        "independence_key": "southern_tia_maria_20260624",
        "independence_rationale": "项目运营方融资、产能和投产时间公告。",
    },
    {
        "source_ref": "fqm_panama_20260407",
        "source_url": "https://www.first-quantum.com/news/government-of-panama-approves-processing-of-stockpiled-ore-at-cobre-panama/",
        "title": "巴拿马政府批准处理Cobre Panamá库存矿石",
        "publisher": "First Quantum Minerals",
        "publish_date": "2026-04-07",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "project_operator_government_approval",
        "independence_key": "fqm_panama_20260407",
        "independence_rationale": "公司转述巴拿马政府正式批准，明确库存处理不构成矿山重启。",
    },
    {
        "source_ref": "chile_royalty",
        "source_url": "https://www.hacienda.cl/noticias-y-eventos/noticias/1-de-enero-entra-en-vigor-nueva-ley-de-royalty-a-la-mineria",
        "title": "智利新矿业特许税法生效",
        "publisher": "Ministerio de Hacienda de Chile",
        "publish_date": "2024-01-02",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "es",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_policy",
        "independence_key": "chile_mining_royalty_2024",
        "independence_rationale": "智利财政部对生效税制的官方说明。",
    },
    {
        "source_ref": "drc_eiti",
        "source_url": "https://eiti.org/countries/democratic-republic-congo",
        "title": "刚果（金）采掘业收入与矿业权利金分配",
        "publisher": "Extractive Industries Transparency Initiative",
        "publish_date": "2026-07-25",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": False,
        "source_credibility": "international_transparency_standard_country_page",
        "independence_key": "eiti_drc_mining_code_revenue_distribution",
        "independence_rationale": "EITI基于刚果（金）2018年矿法整理的权利金分配。",
    },
    {
        "source_ref": "whitehouse_copper_232",
        "source_url": "https://www.whitehouse.gov/fact-sheets/2025/07/fact-sheet-president-donald-j-trump-takes-action-to-address-the-threat-to-national-security-from-imports-of-copper/",
        "title": "美国铜产品232措施说明",
        "publisher": "The White House",
        "publish_date": "2025-07-30",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_policy",
        "independence_key": "us_copper_section_232_20250730",
        "independence_rationale": "美国政府关于税率、豁免与国内销售要求的原始说明。",
    },
    {
        "source_ref": "bhp_ar2025",
        "source_url": "https://www.bhp.com/-/media/documents/investors/annual-reports/2025/250819_bhpannualreport2025",
        "title": "BHP 2025年度报告",
        "publisher": "BHP",
        "publish_date": "2025-08-19",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "bhp_ar2025",
        "independence_rationale": "公司经审计年度报告中的铜资产产量。",
    },
    {
        "source_ref": "codelco_results_2025",
        "source_url": "https://www.codelco.com/en/prensa/2026/codelco-cerro-2025-con-un-ebitda-de-us-6-670-millones-una-utilidad",
        "title": "Codelco 2025年经营业绩",
        "publisher": "Codelco",
        "publish_date": "2026-03-27",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "es",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_results_release",
        "independence_key": "codelco_results_2025",
        "independence_rationale": "公司对自有产量、参股产量和经营结果的正式披露。",
    },
    {
        "source_ref": "codelco_audit_2025",
        "source_url": "https://www.codelco.com/en/prensa/2026/codelco-adopta-medidas-tras-detectar-desviaciones-en-produccion-2025",
        "title": "Codelco说明2025年产量报告偏差及整改",
        "publisher": "Codelco",
        "publish_date": "2026-06-24",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "es",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_audit_release",
        "independence_key": "codelco_2025_production_audit",
        "independence_rationale": "公司对产量报告偏差、影响范围和整改的正式说明。",
    },
    {
        "source_ref": "fcx_10k_2025",
        "source_url": "https://www.sec.gov/Archives/edgar/data/831259/000083125926000012/fcx-20251231.htm",
        "title": "Freeport-McMoRan 2025年10-K",
        "publisher": "U.S. Securities and Exchange Commission",
        "publish_date": "2026-02-13",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "regulatory_filing",
        "independence_key": "fcx_10k_2025",
        "independence_rationale": "SEC申报文件同时披露合并产量和归属于非控股股东的产量。",
    },
    {
        "source_ref": "southern_results_2025",
        "source_url": "https://southerncoppercorp.com/eng/wp-content/uploads/sites/2/2026/01/pr260127.pdf",
        "title": "Southern Copper 2025年经营业绩",
        "publisher": "Southern Copper",
        "publish_date": "2026-01-27",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_results_release",
        "independence_key": "southern_results_2025",
        "independence_rationale": "公司年度产量、利润率和现金流正式披露。",
    },
    {
        "source_ref": "rio_production_2025",
        "source_url": "https://www.riotinto.com/en/news/releases/2026/rio-tinto-releases-fourth-quarter-2025-production-results",
        "title": "Rio Tinto 2025年第四季度生产报告",
        "publisher": "Rio Tinto",
        "publish_date": "2026-01-20",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "rio_production_2025",
        "independence_rationale": "公司年度铜产量正式披露。",
    },
    {
        "source_ref": "glencore_production_2025",
        "source_url": "https://www.glencore.com/media-and-insights/news/full-year-2025-production-report",
        "title": "Glencore 2025年全年生产报告",
        "publisher": "Glencore",
        "publish_date": "2026-01-29",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "glencore_production_2025",
        "independence_rationale": "公司自有来源铜产量正式披露。",
    },
    {
        "source_ref": "anglo_production_2025",
        "source_url": "https://www.angloamerican.com/media/press-releases/2026/05-02-2026",
        "title": "Anglo American 2025年生产报告",
        "publisher": "Anglo American",
        "publish_date": "2026-02-05",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "anglo_production_2025",
        "independence_rationale": "公司年度铜产量正式披露。",
    },
    {
        "source_ref": "antofagasta_production_2025",
        "source_url": "https://prod.antofagasta.co.uk/investors/news/2026/q4-2025-production-report/",
        "title": "Antofagasta 2025年第四季度生产报告",
        "publisher": "Antofagasta",
        "publish_date": "2026-01-21",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "antofagasta_production_2025",
        "independence_rationale": "公司年度铜产量正式披露。",
    },
    {
        "source_ref": "teck_production_2025",
        "source_url": "https://www.teck.com/news/news-releases/2026/teck-announces-2025-production-and-sales-update-and-reaffirms-outlook",
        "title": "Teck 2025年产量与销售更新",
        "publisher": "Teck Resources",
        "publish_date": "2026-01-21",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "teck_production_2025",
        "independence_rationale": "公司按持股比例披露的年度铜产量。",
    },
    {
        "source_ref": "fqm_production_2025",
        "source_url": "https://www.first-quantum.com/news/first-quantum-minerals-announces-2025-preliminary-production-and-2026-2028-guidance/",
        "title": "First Quantum 2025年初步产量与2026—2028年指引",
        "publisher": "First Quantum Minerals",
        "publish_date": "2026-01-19",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "fqm_production_2025",
        "independence_rationale": "公司年度铜产量和未来产量指引。",
    },
    {
        "source_ref": "china_nbs_2025",
        "source_url": "https://www.stats.gov.cn/xxgk/tjgb2020/202602/t20260228_1962662.html",
        "title": "中华人民共和国2025年国民经济和社会发展统计公报",
        "publisher": "国家统计局",
        "publish_date": "2026-02-28",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_statistics",
        "independence_key": "china_nbs_2025",
        "independence_rationale": "国家统计局对2025年精炼铜产量的正式统计。",
    },
    {
        "source_ref": "western_mining_ar2025",
        "source_url": "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?CompanyCode=80055878&gather=1&id=12017335",
        "title": "西部矿业2025年年度报告",
        "publisher": "西部矿业",
        "publish_date": "2026-03-26",
        "source_type": "公告",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "western_mining_ar2025",
        "independence_rationale": "上交所披露的公司经审计年度报告镜像，包含矿产铜年度产量。",
    },
    {
        "source_ref": "china_gold_intl_jiama_2025",
        "source_url": "https://www.chinagoldintl.com/operations/jlama/",
        "title": "中国黄金国际甲玛铜金多金属矿2025年生产更新",
        "publisher": "中国黄金国际",
        "publish_date": "2026-03-31",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_operating_report",
        "independence_key": "china_gold_intl_jiama_2025",
        "independence_rationale": "公司项目页披露甲玛矿2025年铜产量；仅代表该上市主体和项目，不外推集团全部铜矿。",
    },
    {
        "source_ref": "jiangxi_copper_ar2025",
        "source_url": "https://www.jxcc.com/periodicReports/details_512_6694.html",
        "title": "江西铜业2025年年度报告",
        "publisher": "江西铜业",
        "publish_date": "2026-03-27",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "jiangxi_copper_ar2025",
        "independence_rationale": "公司年度报告中的阴极铜和自有矿山铜产量。",
    },
    {
        "source_ref": "tongling_copper_ar2025",
        "source_url": "https://disc.static.szse.cn/disc/disk03/finalpage/2026-04-20/9ce9a44c-195c-4f7c-a489-22ae9fd25950.PDF",
        "title": "铜陵有色2025年年度报告",
        "publisher": "铜陵有色",
        "publish_date": "2026-04-20",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "tongling_copper_ar2025",
        "independence_rationale": "公司年度报告中的阴极铜和自有矿山铜产量。",
    },
    {
        "source_ref": "yunnan_copper_ar2025",
        "source_url": "https://static.cninfo.com.cn/finalpage/2026-03-27/1225037817.PDF",
        "title": "云南铜业2025年年度报告",
        "publisher": "云南铜业",
        "publish_date": "2026-03-27",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "audited_company_filing",
        "independence_key": "yunnan_copper_ar2025",
        "independence_rationale": "公司年度报告中的阴极铜产量。",
    },
    {
        "source_ref": "china_daye_results_2025",
        "source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0331/2026033103505.pdf",
        "title": "中国大冶有色2025年年度业绩",
        "publisher": "中国大冶有色金属矿业",
        "publish_date": "2026-03-31",
        "source_type": "website_material",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "listed_company_filing",
        "independence_key": "china_daye_results_2025",
        "independence_rationale": "港交所披露的年度阴极铜和矿产铜产量。",
    },
    {
        "source_ref": "smm_smelter_2025",
        "source_url": "https://finance.sina.com.cn/wm/2026-06-05/doc-iniakfhk2709527.shtml",
        "title": "2025年中国上市铜冶炼企业产量汇总",
        "publisher": "SMM",
        "publish_date": "2026-06-05",
        "source_type": "website_material",
        "quality_tier": 2,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": False,
        "source_credibility": "industry_data_compilation",
        "independence_key": "smm_listed_copper_smelters_2025",
        "independence_rationale": "SMM按上市公司年报汇总冶炼产量；仅用于统一企业边界和补充金川体系口径。",
    },
]


def _dp(
    source_ref: str,
    metric: str,
    period: str,
    unit: str,
    value: float,
    excerpt: str,
    *,
    company: str | None = None,
    forecast: bool = False,
    inferred: bool = False,
    scope: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    return {
        "source_ref": source_ref,
        "company": company,
        "metric": metric,
        "period": period,
        "unit": unit,
        "value_num": value,
        "value_text": None,
        "source_excerpt": excerpt,
        "extraction_method": "inferred" if inferred else (
            "web_fetch"
            if next(s for s in SOURCE_SPECS if s["source_ref"] == source_ref).get(
                "source_url"
            )
            else "pdf_direct"
        ),
        "is_forecast": forecast,
        "note": note,
        "scope_key": scope or metric,
    }


def build_data_points() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    icsg = {
        2025: (23.197, 28.656, 28.201, 0.455),
        2026: (23.559, 28.760, 28.664, 0.096),
        2027: (24.103, 29.613, 29.236, 0.377),
    }
    for year, (mine, refined, usage, balance) in icsg.items():
        status = "估计" if year == 2025 else "预测"
        excerpt = (
            f"ICSG 2026年4月{status}：{year}年全球矿山铜{mine:.3f}百万吨、"
            f"精炼铜产量{refined:.3f}百万吨、消费{usage:.3f}百万吨，"
            f"供需余额为供应过剩{balance:.3f}百万吨。"
        )
        for metric, value in (
            ("全球矿山铜产量", mine),
            ("全球精炼铜产量", refined),
            ("全球精炼铜消费", usage),
            ("全球精炼铜供需余额", balance),
        ):
            rows.append(
                _dp(
                    "icsg_forecast_20260423",
                    metric,
                    str(year),
                    "百万吨",
                    value,
                    excerpt,
                    forecast=year >= 2026,
                    scope=f"icsg_global_{metric}",
                )
            )

    july_facts = [
        ("2025", "全球矿山铜产量", "百万吨", 23.216),
        ("2026年1—5月", "全球矿山铜产量", "百万吨", 9.377),
        ("2026年1—5月", "全球矿山铜产量同比", "%", -1.9),
        ("2025", "全球矿山产能利用率", "%", 81.0),
        ("2026年1—5月", "全球矿山产能利用率", "%", 76.6),
        ("2025", "全球精炼铜产量", "百万吨", 28.665),
        ("2025", "全球精炼铜消费", "百万吨", 28.196),
        ("2025", "全球精炼铜供需余额", "百万吨", 0.469),
        ("2026年1—5月", "全球精炼铜产量", "百万吨", 12.055),
        ("2026年1—5月", "全球精炼铜消费", "百万吨", 11.834),
        ("2026年1—5月", "全球精炼铜供需余额", "百万吨", 0.221),
        ("2026年5月末", "三大交易所及保税库存", "百万吨", 2.132),
        ("2025年12月末", "三大交易所及保税库存", "百万吨", 1.361),
        ("2026年1—5月", "再生精炼铜占精炼产量", "%", 17.8),
        ("2026年5月", "LME铜月均价", "美元/吨", 13507.0),
    ]
    for period, metric, unit, value in july_facts:
        rows.append(
            _dp(
                "icsg_july_global_2026",
                metric,
                period,
                unit,
                value,
                (
                    "ICSG 2026年7月月报显示，2026年1—5月矿端产量同比下降、"
                    "矿山利用率低于2025年，精炼端仍有表观过剩且库存上升。"
                ),
                scope=f"icsg_july_{metric}",
            )
        )

    country_rows = [
        ("智利", 5300, 180000),
        ("刚果（金）", 3200, 80000),
        ("秘鲁", 2700, 85000),
        ("中国", 1800, 41000),
        ("俄罗斯", 1300, 80000),
        ("赞比亚", 940, 21000),
        ("澳大利亚", 730, 100000),
        ("印度尼西亚", 710, 21000),
    ]
    for country, production, reserves in country_rows:
        excerpt = (
            f"USGS 2026摘要估计{country}2025年矿山铜产量{production}千吨、"
            f"铜储量{reserves}千吨；全球分别约23000千吨和980000千吨。"
        )
        rows.extend(
            [
                _dp(
                    "usgs_mcs_2026",
                    f"{country}矿山铜产量",
                    "2025",
                    "千吨",
                    production,
                    excerpt,
                    scope="usgs_country_mine_production",
                ),
                _dp(
                    "usgs_mcs_2026",
                    f"{country}铜储量",
                    "2025",
                    "千吨",
                    reserves,
                    excerpt,
                    scope="usgs_country_reserves",
                ),
                _dp(
                    "usgs_mcs_2026",
                    f"{country}全球矿山产量占比",
                    "2025",
                    "%",
                    round(production / 23000 * 100, 2),
                    excerpt,
                    inferred=True,
                    scope="usgs_country_mine_share",
                    note="该国矿山产量占比＝该国产量÷USGS全球矿山产量23000千吨。",
                ),
            ]
        )
    for metric, unit, value in (
        ("美国矿山铜产量", "百万吨", 1.0),
        ("美国精炼铜产量", "百万吨", 0.85),
        ("美国精炼铜进口", "百万吨", 1.7),
        ("美国精炼铜净进口依赖度", "%", 57.0),
        ("美国建筑用铜占比", "%", 42.0),
        ("美国电气电子用铜占比", "%", 23.0),
        ("美国交通用铜占比", "%", 18.0),
        ("美国一般消费用铜占比", "%", 10.0),
        ("美国机械用铜占比", "%", 7.0),
    ):
        rows.append(
            _dp(
                "usgs_mcs_2026",
                metric,
                "2025",
                unit,
                value,
                "USGS给出美国2025年铜供需、进口依赖和终端用途结构。",
                scope="usgs_us_copper",
            )
        )

    global_company_rows = [
        ("BHP", 2017.000, "bhp_ar2025", "公司资产合计/运营展示口径"),
        ("Freeport-McMoRan", 1534.503, "fcx_10k_2025", "合并口径"),
        ("Codelco", 1439.732, "codelco_results_2025", "自有加参股归属口径"),
        ("紫金矿业", 1085.126, "zijin_ar2025", "公司披露矿产铜口径"),
        ("Southern Copper", 954.270, "southern_results_2025", "公司产量口径"),
        ("Rio Tinto", 883.000, "rio_production_2025", "公司合并展示口径"),
        ("Glencore", 851.600, "glencore_production_2025", "自有来源口径"),
        ("洛阳钼业", 741.149, "cmoc_ar2025", "公司披露矿产铜口径"),
        ("Anglo American", 695.000, "anglo_production_2025", "公司产量口径"),
        ("Antofagasta", 653.700, "antofagasta_production_2025", "公司产量口径"),
        ("五矿资源", 505.745, "mmg_ar2025", "三座主要矿山100%产量合计"),
        ("Teck Resources", 453.500, "teck_production_2025", "公司应占产量口径"),
        ("First Quantum", 396.000, "fqm_production_2025", "公司产量口径"),
    ]
    for company_name, production, source, reporting_scope in global_company_rows:
        excerpt = (
            f"{company_name}披露2025年铜产量{production:.3f}千吨，"
            f"报告边界为{reporting_scope}。"
        )
        rows.extend(
            [
                _dp(
                    source,
                    f"{company_name}铜产量",
                    "2025",
                    "千吨",
                    production,
                    excerpt,
                    scope="global_company_mine_production_2025",
                ),
                _dp(
                    source,
                    f"{company_name}全球矿山铜产量占比",
                    "2025",
                    "%",
                    round(production / 23000 * 100, 4),
                    excerpt,
                    inferred=True,
                    scope="global_company_mine_share_2025",
                    note=(
                        f"公司份额＝{production:.3f}千吨÷USGS全球矿山铜产量23000千吨。"
                        f"分子为{reporting_scope}，用于规模比较，不等同于股东权益份额。"
                    ),
                ),
            ]
        )

    global_concentration_rows = [
        (
            "全球矿企CR3（公司披露/运营口径）",
            21.701,
            "前三名为BHP、Freeport-McMoRan和Codelco；"
            "CR3＝(2017.000＋1534.503＋1439.732)÷23000。",
        ),
        (
            "全球矿企CR5（公司披露/运营口径）",
            30.568,
            "前五名再加入紫金矿业和Southern Copper；"
            "CR5＝(2017.000＋1534.503＋1439.732＋1085.126＋954.270)÷23000。",
        ),
        (
            "全球矿企CR3（权益/归属代理口径）",
            17.305,
            "前三名使用BHP权益代理1462.718千吨、Codelco含参股归属1439.732千吨、"
            "Freeport归属母公司1077.735千吨；CR3＝三者合计÷23000。",
        ),
        (
            "全球矿企CR5（权益/归属代理口径）",
            25.304,
            "前五名在权益/归属代理前三名基础上加入Southern Copper 954.270千吨"
            "和紫金矿业权益产量885.569千吨；CR5＝五者合计÷23000。",
        ),
    ]
    for metric, value, formula in global_concentration_rows:
        rows.append(
            _dp(
                "usgs_mcs_2026",
                metric,
                "2025",
                "%",
                value,
                (
                    "本研究以公司2025年正式披露的铜产量为分子、"
                    "USGS全球矿山铜产量23000千吨为共同分母复算集中度。"
                ),
                inferred=True,
                scope="global_company_copper_concentration_2025",
                note=(
                    formula
                    + " 两组结果的差异来自合资矿运营口径与股东权益口径，"
                    "是统计边界敏感性，不是置信区间。"
                ),
            )
        )

    # 中国境内矿山企业竞争必须与“中国企业的全球铜产量”分开。
    # 这里使用运营/并表矿山产量代理，避免把洛钼、五矿资源的海外矿山
    # 误写成中国境内矿山供给。江西铜业的年度披露包含第一量子权益量，
    # 因此先扣除该海外权益量；这是可复算代理，不伪装成公司直接披露值。
    china_domestic_mine_rows = [
        (
            "紫金矿业",
            429.809,
            "zijin_ar2025",
            "巨龙193.820＋多宝山112.018＋紫金山85.741＋阿舍勒31.672＋珲春6.558；"
            "不计仅按权益披露且由西部矿业运营的玉龙34.094千吨，避免重复。",
            False,
        ),
        (
            "江西铜业",
            196.7588,
            "jiangxi_copper_ar2025",
            "境内矿山代理＝自产铜精矿含铜269.900－第一量子2025年铜产量396.000"
            "×江西铜业持股18.47%。",
            True,
        ),
        (
            "西部矿业",
            167.500,
            "western_mining_ar2025",
            "公司2025年年度报告披露矿产铜16.75万吨，核心为境内玉龙铜矿等资产。",
            False,
        ),
        (
            "中国黄金国际",
            70.883,
            "china_gold_intl_jiama_2025",
            "公司项目页披露西藏甲玛矿2025年产铜70,883吨；"
            "仅代表中国黄金国际上市主体，不代表中国黄金集团全部铜矿。",
            False,
        ),
    ]
    for company_name, production, source, calculation, inferred in china_domestic_mine_rows:
        excerpt = (
            f"{company_name}2025年中国境内矿山铜运营/并表产量代理为"
            f"{production:.3f}千吨。"
        )
        rows.extend(
            [
                _dp(
                    source,
                    f"{company_name}中国境内矿山铜产量代理",
                    "2025",
                    "千吨",
                    production,
                    excerpt,
                    # 只有已存在完整证券身份和财务画像的紫金矿业建立
                    # company_id 语义链接；其余竞争者保留为行业事实和正文
                    # 表格，避免 ingest 自动创建无 ticker 的空公司页。
                    company=company_name if company_name == "紫金矿业" else None,
                    inferred=inferred,
                    scope="china_domestic_company_mine_production_2025",
                    note=calculation,
                ),
                _dp(
                    source,
                    f"{company_name}中国境内矿山铜产量占比代理",
                    "2025",
                    "%",
                    round(production / 1800 * 100, 4),
                    excerpt,
                    company=company_name if company_name == "紫金矿业" else None,
                    inferred=True,
                    scope="china_domestic_company_mine_share_2025",
                    note=(
                        f"境内份额＝{production:.4f}千吨÷USGS中国2025年矿山铜"
                        f"1800千吨。{calculation}"
                    ),
                ),
            ]
        )
    rows.append(
        _dp(
            "usgs_mcs_2026",
            "中国境内矿山铜企业CR3代理",
            "2025",
            "%",
            44.115,
            (
                "公开同口径样本中，紫金矿业、江西铜业和西部矿业的"
                "中国境内矿山铜运营/并表产量代理合计794.068千吨。"
            ),
            inferred=True,
            scope="china_domestic_company_mine_concentration_2025",
            note=(
                "CR3代理＝(429.809＋196.7588＋167.500)÷USGS中国矿山铜1800＝44.115%。"
                "江西铜业分子扣除了第一量子权益量；USGS分母为四舍五入后的国家估计，"
                "因此该结果用于判断集中度量级，不作为审计级市场份额。"
            ),
        )
    )

    china_smelter_rows = [
        ("江西铜业", 2380.4, "jiangxi_copper_ar2025", "公司年度报告"),
        ("铜陵有色", 1954.8, "tongling_copper_ar2025", "公司年度报告"),
        ("云南铜业", 1641.1, "yunnan_copper_ar2025", "公司年度报告"),
        ("金川体系", 1565.0, "smm_smelter_2025", "SMM按年报统一的集团/体系口径"),
        ("中国大冶", 719.0, "china_daye_results_2025", "港交所年度业绩"),
    ]
    rows.append(
        _dp(
            "china_nbs_2025",
            "中国精炼铜产量",
            "2025",
            "千吨",
            14720.0,
            "国家统计局披露2025年中国精炼铜产量1472万吨，同比增长10.4%。",
            scope="china_refined_copper_production_2025",
        )
    )
    for company_name, production, source, reporting_scope in china_smelter_rows:
        excerpt = (
            f"{company_name}2025年阴极铜产量为{production:.1f}千吨；"
            f"分子采用{reporting_scope}。"
        )
        rows.extend(
            [
                _dp(
                    source,
                    f"{company_name}阴极铜产量",
                    "2025",
                    "千吨",
                    production,
                    excerpt,
                    scope="china_company_cathode_production_2025",
                ),
                _dp(
                    source,
                    f"{company_name}中国精炼铜产量占比",
                    "2025",
                    "%",
                    round(production / 14720 * 100, 4),
                    excerpt,
                    inferred=True,
                    scope="china_company_cathode_share_2025",
                    note=(
                        f"公司份额＝{production:.1f}千吨÷国家统计局中国精炼铜产量14720千吨。"
                    ),
                ),
            ]
        )
    for metric, value, formula in (
        (
            "中国精炼铜企业CR3",
            40.600,
            "CR3＝(2380.4＋1954.8＋1641.1)÷14720。",
        ),
        (
            "中国精炼铜企业CR5",
            56.116,
            "CR5＝(2380.4＋1954.8＋1641.1＋1565.0＋719.0)÷14720。",
        ),
    ):
        rows.append(
            _dp(
                "smm_smelter_2025",
                metric,
                "2025",
                "%",
                value,
                (
                    "本研究把前五家2025年阴极铜产量统一到国家统计局14720千吨分母；"
                    "前三家分子来自公司年报，金川体系使用SMM年报汇总口径。"
                ),
                inferred=True,
                scope="china_company_cathode_concentration_2025",
                note=(
                    formula
                    + " CR5受金川上市主体与集团统计边界影响，应视为统一口径估算；"
                    "CR3的三家公司分子均可由正式公司披露复核。"
                ),
            )
        )

    iea_facts = [
        ("2035", "铜供应相对需求缺口", "%", 25.0),
        ("2025—2040", "全球铜需求增加量", "百万吨", 7.0),
        ("2025", "铜矿资本开支同比", "%", 8.0),
        ("2026", "铜精矿年度长协TC基准", "美元/吨", 0.0),
        ("当前", "再生铜满足需求占比", "%", 10.0),
        ("2040", "再生铜满足需求占比", "%", 20.0),
        ("2025", "拉丁美洲占全球矿山铜产量", "%", 40.0),
        ("2025", "中国占全球冶炼能力", "%", 50.0),
        ("2005", "中国占全球冶炼能力", "%", 15.0),
        ("2025", "中国冶炼产能利用率", "%", 85.0),
        ("2025", "中国以外冶炼产能利用率", "%", 70.0),
    ]
    for period, metric, unit, value in iea_facts:
        rows.append(
            _dp(
                "iea_gcm_2026",
                metric,
                period,
                unit,
                value,
                (
                    "IEA 2026展望强调矿山开发周期、冶炼扩张集中和电气化需求共同造成"
                    "中长期铜供给压力。"
                ),
                forecast=period in {"2035", "2040", "2025—2040"},
                scope="iea_copper_outlook",
            )
        )

    zijin_ops = [
        ("2025", "矿产铜产量", "千吨", 1085.126),
        ("2025", "权益矿产铜产量", "千吨", 885.569),
        ("2026Q1", "矿产铜产量", "千吨", 259.214),
        ("2026Q1", "Kamoa权益矿产铜产量", "千吨", 27.361),
        ("2026指引", "矿产铜产量", "千吨", 1200.0),
        ("2028目标", "矿产铜产量下限", "千吨", 1500.0),
        ("2028目标", "矿产铜产量上限", "千吨", 1600.0),
        ("2026指引", "矿产金产量", "吨", 105.0),
        ("2026指引", "碳酸锂当量产量", "千吨", 120.0),
    ]
    for period, metric, unit, value in zijin_ops:
        source = "zijin_q1_2026" if "Q1" in period else "zijin_ar2025"
        rows.append(
            _dp(
                source,
                metric,
                period,
                unit,
                value,
                "紫金矿业年度报告和季度报告披露矿产铜、权益产量及中期产量目标。",
                company="紫金矿业",
                forecast="指引" in period or "目标" in period,
                scope="zijin_operating_guidance",
            )
        )

    cmoc_ops = [
        ("2025", "矿产铜产量", "千吨", 741.149),
        ("2026Q1", "矿产铜产量", "千吨", 187.88),
        ("2026指引", "矿产铜产量下限", "千吨", 760.0),
        ("2026指引", "矿产铜产量上限", "千吨", 820.0),
        ("2025", "铜矿业务毛利率", "%", 55.16),
        ("2027目标", "KFM二期新增铜产能", "千吨/年", 100.0),
        ("项目预算", "KFM二期资本开支", "亿美元", 10.84),
    ]
    for period, metric, unit, value in cmoc_ops:
        source = "cmoc_q1_2026" if "Q1" in period else "cmoc_ar2025"
        rows.append(
            _dp(
                source,
                metric,
                period,
                unit,
                value,
                "洛阳钼业年度报告和季度报告披露TFM/KFM产量、业务毛利率与扩产计划。",
                company="洛阳钼业",
                forecast=period in {"2026指引", "2027目标", "项目预算"},
                scope="cmoc_operating_guidance",
            )
        )

    mmg_ops = [
        ("2025", "Las Bambas铜产量", "千吨", 410.834, "mmg_ar2025"),
        ("2025", "Las Bambas C1现金成本", "美元/磅", 1.12, "mmg_ar2025"),
        ("2025", "Kinsevere铜产量", "千吨", 52.791, "mmg_ar2025"),
        ("2025", "Kinsevere C1现金成本", "美元/磅", 3.12, "mmg_ar2025"),
        ("2025", "Khoemacau铜产量", "千吨", 42.120, "mmg_ar2025"),
        ("2025", "Khoemacau C1现金成本", "美元/磅", 1.97, "mmg_ar2025"),
        ("2026指引", "Las Bambas铜产量下限", "千吨", 380.0, "mmg_q2_2026"),
        ("2026指引", "Las Bambas铜产量上限", "千吨", 400.0, "mmg_q2_2026"),
        ("2026指引", "Las Bambas C1现金成本下限", "美元/磅", 0.85, "mmg_q2_2026"),
        ("2026指引", "Las Bambas C1现金成本上限", "美元/磅", 1.05, "mmg_q2_2026"),
        ("2026H1", "Las Bambas铜产量", "千吨", 210.195, "mmg_q2_2026"),
        ("2026H1", "Las Bambas C1现金成本", "美元/磅", 0.55, "mmg_q2_2026"),
        ("2026H1", "Kinsevere铜产量", "千吨", 33.8, "mmg_q2_2026"),
        ("2026H1", "Khoemacau铜产量", "千吨", 22.083, "mmg_q2_2026"),
        ("2028目标", "Khoemacau扩产后铜产能", "千吨/年", 130.0, "mmg_q2_2026"),
    ]
    for period, metric, unit, value, source in mmg_ops:
        rows.append(
            _dp(
                source,
                metric,
                period,
                unit,
                value,
                "五矿资源年度报告及2026年第二季度生产报告披露三座主要矿山产量、成本和扩产。",
                company="五矿资源",
                forecast=period in {"2026指引", "2028目标"},
                scope="mmg_operating_guidance",
            )
        )

    project_facts = [
        (
            "ivanhoe_kamoa_20260331",
            "Kamoa-Kakula 2026产量指引下限",
            "2026",
            "千吨",
            290.0,
        ),
        (
            "ivanhoe_kamoa_20260331",
            "Kamoa-Kakula 2026产量指引上限",
            "2026",
            "千吨",
            330.0,
        ),
        (
            "ivanhoe_kamoa_20260331",
            "Kamoa-Kakula 2027产量指引下限",
            "2027",
            "千吨",
            380.0,
        ),
        (
            "ivanhoe_kamoa_20260331",
            "Kamoa-Kakula 2027产量指引上限",
            "2027",
            "千吨",
            420.0,
        ),
        (
            "ivanhoe_kamoa_20260331",
            "Kamoa-Kakula 2028年化产量目标",
            "2028",
            "千吨",
            500.0,
        ),
        (
            "rio_oyu_20260630",
            "Oyu Tolgoi平均铜产量",
            "2028—2036",
            "千吨/年",
            500.0,
        ),
        (
            "fcx_grasberg_restart",
            "Grasberg 2026铜产量指引",
            "2026",
            "十亿磅",
            1.0,
        ),
        (
            "fcx_grasberg_restart",
            "Grasberg 2027—2029平均铜产量",
            "2027—2029",
            "十亿磅/年",
            1.6,
        ),
        (
            "bhp_escondida_20260317",
            "Escondida新选厂产能下限",
            "2031—2032",
            "千吨/年",
            220.0,
        ),
        (
            "bhp_escondida_20260317",
            "Escondida新选厂产能上限",
            "2031—2032",
            "千吨/年",
            260.0,
        ),
        (
            "bhp_escondida_20260317",
            "Escondida新选厂资本开支下限",
            "项目预算",
            "十亿美元",
            4.4,
        ),
        (
            "bhp_escondida_20260317",
            "Escondida新选厂资本开支上限",
            "项目预算",
            "十亿美元",
            5.9,
        ),
        (
            "teck_qb_outlook",
            "Quebrada Blanca 2026产量指引下限",
            "2026",
            "千吨",
            200.0,
        ),
        (
            "teck_qb_outlook",
            "Quebrada Blanca 2026产量指引上限",
            "2026",
            "千吨",
            235.0,
        ),
        (
            "teck_qb_outlook",
            "Quebrada Blanca 2027产量指引下限",
            "2027",
            "千吨",
            240.0,
        ),
        (
            "teck_qb_outlook",
            "Quebrada Blanca 2027产量指引上限",
            "2027",
            "千吨",
            275.0,
        ),
        (
            "southern_tia_maria_20260624",
            "Tía María设计产能",
            "2027目标",
            "千吨/年",
            120.0,
        ),
        (
            "fqm_panama_20260407",
            "Cobre Panamá库存矿处理预期产铜下限",
            "2026",
            "千吨",
            30.0,
        ),
        (
            "fqm_panama_20260407",
            "Cobre Panamá库存矿处理预期产铜上限",
            "2026",
            "千吨",
            40.0,
        ),
    ]
    for source, metric, period, unit, value in project_facts:
        rows.append(
            _dp(
                source,
                metric,
                period,
                unit,
                value,
                "项目运营方披露的产量、产能、资本开支或恢复计划。",
                forecast=True,
                scope="global_copper_project_pipeline",
            )
        )

    policy_facts = [
        ("chile_royalty", "智利大型铜矿从价税率", "2024起", "%", 1.0),
        ("chile_royalty", "智利大型矿企综合税负上限", "2024起", "%", 46.5),
        ("drc_eiti", "刚果（金）权利金中央政府分配", "2018矿法", "%", 50.0),
        ("drc_eiti", "刚果（金）权利金省级分配", "2018矿法", "%", 25.0),
        ("drc_eiti", "刚果（金）权利金地方实体分配", "2018矿法", "%", 15.0),
        ("drc_eiti", "刚果（金）权利金未来世代基金分配", "2018矿法", "%", 10.0),
        ("whitehouse_copper_232", "美国铜半成品及衍生品232关税", "2025-08-01起", "%", 50.0),
        ("whitehouse_copper_232", "美国高质量废铜国内销售要求", "2025政策", "%", 25.0),
        ("whitehouse_copper_232", "美国本土铜原料国内销售要求", "2027", "%", 25.0),
        ("whitehouse_copper_232", "美国本土铜原料国内销售要求", "2029", "%", 40.0),
    ]
    for source, metric, period, unit, value in policy_facts:
        rows.append(
            _dp(
                source,
                metric,
                period,
                unit,
                value,
                "政府或EITI公开政策口径；税费和本地销售要求影响利润与地区价差，不直接等同于物理减产。",
                scope="country_policy_copper",
            )
        )

    # 2028—2030年为研究模型：沿用ICSG 2027锚点，逐年加入互斥需求分项。
    demand_rows = {
        2028: (29.876, 30.05, 0.174),
        2029: (30.626, 30.60, -0.026),
        2030: (31.476, 31.15, -0.326),
    }
    for year, (usage, supply, balance) in demand_rows.items():
        note = (
            "模型以ICSG 2027消费29.236百万吨、精炼产量29.613百万吨为锚；"
            "远期消费逐年加入电网、新能源汽车、新能源、数据中心直接用铜、建筑、"
            "一般制造并扣除节材与替代；供给根据已披露项目、爬坡损失与再生铜估算。"
            "完整模型哈希为sha256:05e029475ff455744a55a7fec6fcf10d8b1e4c94b144ab1c72f87e7dcb961c00。"
        )
        excerpt = (
            f"本研究基准估算{year}年精炼铜消费{usage:.3f}百万吨、供给{supply:.3f}百万吨、"
            f"余额{balance:.3f}百万吨。"
        )
        for metric, value in (
            ("本研究全球精炼铜消费", usage),
            ("本研究全球精炼铜供给", supply),
            ("本研究全球精炼铜供需余额", balance),
        ):
            rows.append(
                _dp(
                    "icsg_forecast_20260423",
                    metric,
                    str(year),
                    "百万吨",
                    value,
                    excerpt,
                    forecast=True,
                    inferred=True,
                    scope="internal_copper_balance_model",
                    note=note,
                )
            )

    return rows


KEY_ARGUMENTS = [
    {
        "source_ref": "usgs_mcs_2026",
        "argument": "铜行业必须把国家集中度、矿企集中度和中国冶炼企业集中度分开计算。",
        "support": (
            "按2025年同年数据复算，全球矿企CR3约17%—22%、CR5约25%—31%；"
            "中国精炼铜企业CR3约40.6%、CR5约56.1%。矿企区间来自运营与权益口径差异，"
            "冶炼集中度使用国家统计局1472万吨精炼铜产量作共同分母。"
        ),
        "counter": (
            "全球矿企披露边界并不完全一致，中国CR5的金川集团/上市主体边界也会改变排序，"
            "因此集中度用于刻画结构，不直接等同于定价权。"
        ),
        "sentiment": "中性",
        "dimension": "竞争格局",
    },
    {
        "source_ref": "icsg_forecast_20260423",
        "argument": "2026—2027精炼铜表观余额仍偏宽松，但矿山端已弱于预期。",
        "support": (
            "ICSG春季预测2026年精炼铜过剩9.6万吨、2027年过剩37.7万吨；"
            "7月月报显示2026年1—5月矿山产量同比下降1.9%、利用率降至76.6%。"
        ),
        "counter": "中国未报告库存和地区库存迁移会使表观消费与真实终端需求偏离。",
        "sentiment": "中性",
        "dimension": "供需平衡",
    },
    {
        "source_ref": "usgs_mcs_2026",
        "argument": "中期铜的约束在矿山项目兑现和品位，不在全球地质储量绝对不足。",
        "support": (
            "USGS全球储量约9.8亿吨，远高于当年产量；但Kamoa、QB和Grasberg均展示"
            "地下水、尾矿、恢复与爬坡可使已建项目低于设计产能。"
        ),
        "counter": "高价、回收、替代和项目审批加快可提高有效供给。",
        "sentiment": "看涨",
        "dimension": "供给与成本",
    },
    {
        "source_ref": "iea_gcm_2026",
        "argument": "AI是新增需求之一，不能把全部电网铜需求归因于AI。",
        "support": (
            "本研究将数据中心直接用铜与电网扩容分列；外部报告采用广义AI电力链口径时"
            "显著高于直接用铜口径。"
        ),
        "counter": "若机架功率、电网接入和配套储能同步超预期，广义增量会更高。",
        "sentiment": "中性",
        "dimension": "市场空间",
    },
    {
        "source_ref": "zijin_ar2025",
        "argument": "三家公司不是同一个铜价代理。",
        "support": (
            "紫金有铜金锂组合和全球项目，洛阳钼业有铜钴副产品及IXM贸易，"
            "五矿资源铜纯度高但少数股东、负债和单矿运营风险更强。"
        ),
        "counter": "在极端铜价上涨阶段，三者短期股价相关性可能高于经营结构差异。",
        "sentiment": "中性",
        "dimension": "公司壁垒",
    },
]
