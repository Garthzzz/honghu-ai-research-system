from __future__ import annotations

"""锂电池行业 B 轨研究的来源登记与平行研究事实。

本文件只承载行业装机、出货、竞争、技术、产能、地区暴露和政策事实。
Wind/Tushare/yfinance 的报表、行情、估值和一致预期继续只保存在
``financial.db``，不得从本文件复制进 ``research.db``。
"""

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FILING_MANIFEST = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "sources"
    / "company_filing_manifest_v1.json"
)


WEB_SOURCES: list[dict[str, Any]] = [
    {
        "source_ref": "sne_global_ev_2026m5",
        "source_url": (
            "https://www.sneresearch.com/en/insight/release_view/685/page/0"
            "?s_cat=%7C1%7C2%7C&s_keyword="
        ),
        "title": "Global EV Battery Usage in January–May 2026",
        "title_zh": "2026年1—5月全球动力电池装机",
        "publisher": "SNE Research",
        "publish_date": "2026-07-06",
        "source_type": "行业数据库",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "industry_market_tracker",
        "independence_key": "sne_global_ev_2026m5",
        "independence_rationale": "SNE Research按车辆装机统计的全球动力电池月度数据库。",
    },
    {
        "source_ref": "infolink_ess_2026q1",
        "source_url": (
            "https://www.infolink-group.com/energy-article/"
            "energy-storage-topic-global-battery-shipment-ranking-1q26"
        ),
        "title": "Global energy-storage cell shipment ranking, Q1 2026",
        "title_zh": "2026年一季度全球储能电芯出货排名",
        "publisher": "InfoLink Consulting",
        "publish_date": "2026-05-21",
        "source_type": "行业数据库",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "industry_market_tracker",
        "independence_key": "infolink_global_ess_2026q1",
        "independence_rationale": "InfoLink基于访谈与模型估计的储能电芯出货数据库；方法边界在正文保留。",
    },
    {
        "source_ref": "china_gov_nev_2026h1",
        "source_url": (
            "https://english.www.gov.cn/archive/statistics/202607/09/"
            "content_WS6a4f5a96c6d00ca5f9a0c15a.html"
        ),
        "title": "China's NEV output, sales maintain robust growth in H1",
        "title_zh": "中国2026年上半年新能源汽车产销",
        "publisher": "中国政府网",
        "publish_date": "2026-07-09",
        "source_type": "政府统计",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_statistics",
        "independence_key": "caam_nev_2026h1",
        "independence_rationale": "中国政府网转引中国汽车工业协会2026年上半年产销统计。",
    },
    {
        "source_ref": "fastmarkets_cabia_2026h1",
        "source_url": (
            "https://www.fastmarkets.com/insights/"
            "china-battery-production-surges-53-in-h1-as-energy-storage-"
            "demand-and-exports-drive-growth-beyond-ev-market/"
        ),
        "title": "China battery production surges 53% in H1 2026",
        "title_zh": "中国2026年上半年动力与储能电池产销",
        "publisher": "Fastmarkets",
        "publish_date": "2026-07-20",
        "source_type": "行业媒体",
        "quality_tier": 2,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": False,
        "source_credibility": "secondary_quote_of_industry_association",
        "independence_key": "cabia_2026h1_battery_statistics",
        "independence_rationale": "Fastmarkets转引中国汽车动力电池产业创新联盟统计，按同一底稿只计一个证据组。",
    },
    {
        "source_ref": "askci_china_ev_2026h1",
        "source_url": "https://www.askci.com/news/20260721/093035278459743528218256.shtml",
        "title": "2026年上半年中国动力电池装车量及企业集中度",
        "publisher": "中商产业研究院",
        "publish_date": "2026-07-21",
        "source_type": "行业数据汇编",
        "quality_tier": 2,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": False,
        "source_credibility": "secondary_quote_of_industry_association",
        "independence_key": "cabia_2026h1_company_ranking",
        "independence_rationale": "转引中国汽车动力电池产业创新联盟企业装车排名；不与同底稿转载重复计权。",
    },
    {
        "source_ref": "ess_news_314ah_price_202604",
        "source_url": (
            "https://www.ess-news.com/2026/04/22/"
            "chinas-314-ah-storage-cell-prices-climb-more-than-20-in-six-months/"
        ),
        "title": "China's 314 Ah storage cell prices climb more than 20%",
        "title_zh": "中国314Ah储能电芯价格半年上涨超过20%",
        "publisher": "ESS News",
        "publish_date": "2026-04-22",
        "source_type": "行业媒体",
        "quality_tier": 2,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": False,
        "source_credibility": "specialist_industry_media",
        "independence_key": "ess_news_314ah_price_202604",
        "independence_rationale": "储能专业媒体对314Ah电芯报价的时点记录；用于价格方向，不替代合同ASP。",
    },
    {
        "source_ref": "cn_consumption_tax_2026",
        "source_url": (
            "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5251171/content.html"
        ),
        "title": "财政部 海关总署 税务总局公告2026年第20号",
        "publisher": "国家税务总局",
        "publish_date": "2026-07-17",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_regulation",
        "independence_key": "cn_battery_consumption_tax_2026",
        "independence_rationale": "中国电池消费税征收范围、税率、时间与免税技术的政策原文。",
    },
    {
        "source_ref": "cn_export_rebate_2026",
        "source_url": (
            "https://szs.mof.gov.cn/zhengcefabu/202601/t20260109_3981637.htm"
        ),
        "title": "财政部 税务总局公告2026年第2号",
        "publisher": "财政部",
        "publish_date": "2026-01-09",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_regulation",
        "independence_key": "cn_battery_export_rebate_2026",
        "independence_rationale": "电池出口退税调整的财政部政策原文。",
    },
    {
        "source_ref": "irs_clean_vehicle_credit",
        "source_url": "https://www.irs.gov/clean-vehicle-tax-credits",
        "title": "Clean vehicle tax credits",
        "title_zh": "美国清洁车辆税收抵免",
        "publisher": "U.S. Internal Revenue Service",
        "publish_date": "2026-07-01",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_regulation",
        "independence_key": "irs_clean_vehicle_credit_current",
        "independence_rationale": "美国国税局对清洁车辆抵免当前适用期的官方说明。",
    },
    {
        "source_ref": "ustr_battery_tariff",
        "source_url": (
            "https://ustr.gov/about-us/policy-offices/press-office/"
            "press-releases/2024/may/us-trade-representative-katherine-tai-"
            "take-further-action-china-tariffs-after-releasing-statutory"
        ),
        "title": "USTR action following the Section 301 four-year review",
        "title_zh": "美国301关税四年复审后的电池关税安排",
        "publisher": "Office of the U.S. Trade Representative",
        "publish_date": "2024-05-14",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_regulation",
        "independence_key": "ustr_section301_battery_tariff",
        "independence_rationale": "美国贸易代表办公室对中国电动车和非电动车锂电池税率及实施期的官方说明。",
    },
    {
        "source_ref": "irs_45x_final",
        "source_url": "https://www.irs.gov/irb/2024-51_IRB",
        "title": "Final regulations under section 45X",
        "title_zh": "美国先进制造生产抵免45X最终规则",
        "publisher": "U.S. Internal Revenue Service",
        "publish_date": "2024-12-16",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_regulation",
        "independence_key": "irs_section45x_final",
        "independence_rationale": "美国国税局45X电芯与模组抵免金额和退坡规则。",
    },
    {
        "source_ref": "irs_pfe_2026",
        "source_url": "https://www.irs.gov/irb/2026-11_IRB",
        "title": "IRS Notice 2026-15",
        "title_zh": "美国受禁止外国实体限制实施指引",
        "publisher": "U.S. Internal Revenue Service",
        "publish_date": "2026-03-16",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_regulation",
        "independence_key": "irs_pfe_notice_2026_15",
        "independence_rationale": "45X相关受禁止外国实体限制的当前实施指引。",
    },
    {
        "source_ref": "eu_battery_regulation",
        "source_url": "https://eur-lex.europa.eu/eli/reg/2023/1542/oj?locale=en",
        "title": "Regulation (EU) 2023/1542 concerning batteries",
        "title_zh": "欧盟电池与废电池法规",
        "publisher": "European Union",
        "publish_date": "2023-07-28",
        "source_type": "法规原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "supranational_regulation",
        "independence_key": "eu_battery_regulation_2023_1542",
        "independence_rationale": "欧盟电池护照、碳足迹、回收和尽职调查的法规原文。",
    },
    {
        "source_ref": "eu_due_diligence_delay",
        "source_url": (
            "https://www.consilium.europa.eu/en/press/press-releases/2025/"
            "07/18/simplification-council-adopts-law-to-stop-the-clock-on-"
            "due-diligence-rules-for-batteries/"
        ),
        "title": "Council adopts stop-the-clock law for battery due diligence",
        "title_zh": "欧盟理事会通过电池尽职调查延期法案",
        "publisher": "Council of the European Union",
        "publish_date": "2025-07-18",
        "source_type": "法规原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "supranational_regulation",
        "independence_key": "eu_battery_due_diligence_delay",
        "independence_rationale": "欧盟理事会对电池尽职调查生效日的最终立法说明。",
    },
    {
        "source_ref": "eu_battery_booster",
        "source_url": (
            "https://climate.ec.europa.eu/eu-action/eu-funding-climate-action/"
            "innovation-fund/battery-booster-facility_en"
        ),
        "title": "Battery Booster Facility",
        "title_zh": "欧盟电池产业无息贷款工具",
        "publisher": "European Commission",
        "publish_date": "2026-06-01",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "supranational_policy",
        "independence_key": "eu_battery_booster_2026",
        "independence_rationale": "欧盟委员会对Battery Booster规模、项目上限和资格要求的官方说明。",
    },
    {
        "source_ref": "eu_bev_duties",
        "source_url": (
            "https://ec.europa.eu/commission/presscorner/api/files/document/"
            "print/en/ip_24_5589/IP_24_5589_EN.pdf"
        ),
        "title": "Definitive countervailing duties on imports of BEVs from China",
        "title_zh": "欧盟对中国纯电动车最终反补贴税",
        "publisher": "European Commission",
        "publish_date": "2024-10-29",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "supranational_regulation",
        "independence_key": "eu_china_bev_definitive_duties",
        "independence_rationale": "欧盟委员会对中国纯电动车最终企业税率的官方说明。",
    },
    {
        "source_ref": "iea_ev_batteries_2026",
        "source_url": (
            "https://www.iea.org/reports/global-ev-outlook-2026/"
            "electric-vehicle-batteries"
        ),
        "title": "Electric vehicle batteries – Global EV Outlook 2026",
        "title_zh": "《全球电动汽车展望2026》电动汽车电池专题",
        "publisher": "International Energy Agency",
        "publish_date": "2026-05-01",
        "source_type": "国际组织研究",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "intergovernmental_model_and_database",
        "independence_key": "iea_global_ev_outlook_2026",
        "independence_rationale": "IEA基于EV Volumes、Benchmark、BNEF等底层数据库形成的2026年全球电池供需、产能和成本专题；同一报告各章节合并计为一个证据组。",
    },
    {
        "source_ref": "iea_ev_manufacturing_2026",
        "source_url": (
            "https://www.iea.org/reports/global-ev-outlook-2026/"
            "manufacturing-and-trade"
        ),
        "title": "Manufacturing and trade – Global EV Outlook 2026",
        "title_zh": "《全球电动汽车展望2026》制造与贸易专题",
        "publisher": "International Energy Agency",
        "publish_date": "2026-05-01",
        "source_type": "国际组织研究",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "intergovernmental_model_and_database",
        "independence_key": "iea_global_ev_outlook_2026",
        "independence_rationale": "与IEA电池专题共享报告和模型底稿，用于区域产能、贸易、本地化与利用率判断，不重复计独立证据。",
    },
    {
        "source_ref": "iea_ev_summary_2026",
        "source_url": (
            "https://www.iea.org/reports/global-ev-outlook-2026/"
            "executive-summary"
        ),
        "title": "Executive summary – Global EV Outlook 2026",
        "title_zh": "《全球电动汽车展望2026》执行摘要",
        "publisher": "International Energy Agency",
        "publish_date": "2026-05-01",
        "source_type": "国际组织研究",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "intergovernmental_model_and_database",
        "independence_key": "iea_global_ev_outlook_2026",
        "independence_rationale": "与IEA电池专题共享报告和模型底稿，用于全球新能源汽车销量、区域增速与政策情景，不重复计独立证据。",
    },
    {
        "source_ref": "iea_critical_minerals_2026",
        "source_url": (
            "https://www.iea.org/reports/"
            "global-critical-minerals-outlook-2026/executive-summary"
        ),
        "title": "Global Critical Minerals Outlook 2026",
        "title_zh": "《全球关键矿产展望2026》",
        "publisher": "International Energy Agency",
        "publish_date": "2026-07-24",
        "source_type": "国际组织研究",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "intergovernmental_model_and_database",
        "independence_key": "iea_global_critical_minerals_2026",
        "independence_rationale": "IEA对锂、镍、钴、石墨等电池材料供需、精炼集中度、出口限制和投资的独立模型。",
    },
    {
        "source_ref": "cn_battery_norm_2024",
        "source_url": (
            "https://www.miit.gov.cn/zwgk/zcwj/wjfb/gg/art/2024/"
            "art_dfe849c6837c4a50bf3e3c30d1697710.html"
        ),
        "title": "锂离子电池行业规范条件（2024年本）",
        "publisher": "工业和信息化部",
        "publish_date": "2024-06-18",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_regulation",
        "independence_key": "cn_lithium_battery_norm_2024",
        "independence_rationale": "中国锂离子电池制造企业质量、研发、能耗、安全与规范公告管理的活动政策原文。",
    },
    {
        "source_ref": "cn_storage_capacity_price_2026",
        "source_url": "https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=20602",
        "title": "关于完善发电侧容量电价机制的通知",
        "publisher": "国家发展改革委、国家能源局",
        "publish_date": "2026-01-30",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_regulation",
        "independence_key": "cn_generation_capacity_price_2026",
        "independence_rationale": "中国独立新型储能容量电价和可靠容量补偿的国家级规则原文。",
    },
    {
        "source_ref": "cn_battery_recycling_2026",
        "source_url": (
            "https://www.miit.gov.cn/gyhxxhb/jgsj/cyzcyfgs/bmgz/"
            "jdcjxl/art/2026/art_392462fdc40c415ea4a4129cac3028c2.html"
        ),
        "title": "新能源汽车废旧动力电池回收和综合利用管理暂行办法",
        "publisher": "工业和信息化部等六部门",
        "publish_date": "2026-01-16",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_regulation",
        "independence_key": "cn_ev_battery_recycling_2026",
        "independence_rationale": "自2026年4月施行的动力电池回收责任、信息披露和综合利用管理规则。",
    },
    {
        "source_ref": "cn_battery_export_control_2025",
        "source_url": (
            "https://www.mofcom.gov.cn/cms_files/filemanager/"
            "policySummary/viewcore_24600584ed4a4abf8f74d7385d935f3c.html"
        ),
        "title": "商务部 海关总署公告2025年第58号",
        "publisher": "商务部、海关总署",
        "publish_date": "2025-10-09",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_export_control",
        "independence_key": "cn_battery_material_equipment_export_control_2025",
        "independence_rationale": "对达到参数门槛的锂电池、关键设备、正极材料、石墨负极材料及相关技术实行许可管理的原始公告。",
    },
    {
        "source_ref": "cn_battery_tech_export_catalog_2025",
        "source_url": (
            "https://www.most.gov.cn/satp/kjzc/zh/202507/"
            "t20250716_194194.html"
        ),
        "title": "商务部 科技部公告2025年第28号",
        "publisher": "商务部、科学技术部",
        "publish_date": "2025-07-15",
        "source_type": "政策原文",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "zh",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_technology_export_control",
        "independence_key": "cn_restricted_battery_technology_catalog_2025",
        "independence_rationale": "电池正极材料和部分提锂工艺进入限制出口技术目录的原始公告。",
    },
    {
        "source_ref": "eu_battery_passport_2026",
        "source_url": (
            "https://single-market-economy.ec.europa.eu/single-market/"
            "digital-product-passport/batteries_en"
        ),
        "title": "Batteries – Digital Product Passport",
        "title_zh": "欧盟电池数字产品护照实施页",
        "publisher": "European Commission",
        "publish_date": "2026-07-20",
        "source_type": "政策实施说明",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "supranational_policy_implementation",
        "independence_key": "eu_battery_digital_product_passport",
        "independence_rationale": "欧盟委员会对登记系统、适用主体和2027年强制实施时间的当前实施说明。",
    },
    {
        "source_ref": "eu_industrial_accelerator_2026",
        "source_url": (
            "https://commission.europa.eu/news-and-media/news/"
            "commission-proposes-new-measures-boost-eu-industry-and-jobs-"
            "2026-03-04_en"
        ),
        "title": "Commission proposes new measures to boost EU industry and jobs",
        "title_zh": "欧盟委员会产业加速与战略外资条件提案",
        "publisher": "European Commission",
        "publish_date": "2026-03-04",
        "source_type": "政策提案",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "supranational_policy_proposal",
        "independence_key": "eu_industrial_accelerator_proposal_2026",
        "independence_rationale": "尚待欧盟立法机构审议的战略行业外资、本地就业和技术转移提案；只作为前瞻情景，不当作现行法规。",
    },
    {
        "source_ref": "india_acc_pli_2026",
        "source_url": (
            "https://www.pib.gov.in/PressReleasePage.aspx?"
            "PRID=2225877&lang=1&reg=1"
        ),
        "title": "PLI-ACC Scheme",
        "title_zh": "印度先进化学电池生产激励计划进展",
        "publisher": "Press Information Bureau, Government of India",
        "publish_date": "2026-02-10",
        "source_type": "政策实施说明",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_policy_implementation",
        "independence_key": "india_acc_pli_2026",
        "independence_rationale": "印度政府披露ACC电池生产激励总目标、已分配产能、投资与就业进度。",
    },
    {
        "source_ref": "brazil_storage_auction_2026",
        "source_url": (
            "https://www.gov.br/mme/pt-br/assuntos/noticias/"
            "mme-publica-diretrizes-para-leilao-inedito-de-"
            "armazenamento-de-energia-em-baterias-no-brasil"
        ),
        "title": "Brazil publishes guidelines for its first battery storage auction",
        "title_zh": "巴西发布首次电池储能拍卖指引",
        "publisher": "Ministry of Mines and Energy, Brazil",
        "publish_date": "2026-06-03",
        "source_type": "政策实施说明",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "pt",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_policy_implementation",
        "independence_key": "brazil_battery_storage_auction_2026",
        "independence_rationale": "巴西政府对首次电池储能容量拍卖的原始实施说明。",
    },
    {
        "source_ref": "afdb_gotion_morocco_2026",
        "source_url": (
            "https://www.afdb.org/en/news-and-events/"
            "african-development-bank-approves-eu100-million-gotion-"
            "power-morocco-develop-africas-first-lithium-ion-phosphate-"
            "battery-gigafactory-95727"
        ),
        "title": "AfDB approves EUR 100 million for Gotion Power Morocco",
        "title_zh": "非洲开发银行批准国轩摩洛哥电池项目贷款",
        "publisher": "African Development Bank",
        "publish_date": "2026-07-24",
        "source_type": "多边开发金融披露",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "multilateral_project_finance",
        "independence_key": "afdb_gotion_morocco_financing_2026",
        "independence_rationale": "项目融资方对贷款规模、一期产能和扩建目标的原始披露。",
    },
    {
        "source_ref": "portugal_calb_sines_2025",
        "source_url": (
            "https://portugal.gov.pt/pt/gc24/comunicacao/noticias/"
            "fabrica-de-ultima-geracao-de-baterias-de-litio-lancada-em-sines"
        ),
        "title": "Fábrica de última geração de baterias de lítio lançada em Sines",
        "title_zh": "葡萄牙政府披露中创新航Sines电池工厂",
        "publisher": "Government of Portugal",
        "publish_date": "2025-02-24",
        "source_type": "政府项目披露",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "pt",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "government_project_disclosure",
        "independence_key": "portugal_calb_sines_project",
        "independence_rationale": "项目所在国政府对投资额、一期产能、就业和目标投产时间的披露。",
    },
    {
        "source_ref": "gotion_michigan_case_2026",
        "source_url": (
            "https://law.justia.com/cases/federal/appellate-courts/"
            "ca6/24-1783/24-1783-2026-02-25.html"
        ),
        "title": "Gotion, Inc. v. Green Charter Township",
        "title_zh": "国轩美国密歇根项目联邦上诉法院判决",
        "publisher": "U.S. Court of Appeals for the Sixth Circuit",
        "publish_date": "2026-02-25",
        "source_type": "司法文书",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "judicial_record",
        "independence_key": "gotion_michigan_project_litigation",
        "independence_rationale": "联邦上诉法院判决记录项目地方阻力、州政府违约认定和资金返还争议。",
    },
    {
        "source_ref": "eve_malaysia_factory",
        "source_url": "https://www.evebattery.com/en/news-1813",
        "title": "Construction of EVE's Malaysia factory",
        "title_zh": "亿纬锂能马来西亚工厂建设进展",
        "publisher": "EVE Energy",
        "publish_date": "2024-05-09",
        "source_type": "公司项目披露",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_project_disclosure",
        "independence_key": "eve_malaysia_factory",
        "independence_rationale": "亿纬锂能对马来西亚一期投资和储能二期用地的原始披露。",
    },
    {
        "source_ref": "farasis_siro_factory",
        "source_url": "https://www.farasis-energy.com/en/start-of-production/",
        "title": "Siro starts battery module and pack production in Türkiye",
        "title_zh": "孚能科技与Togg合资Siro开始模组和电池包生产",
        "publisher": "Farasis Energy",
        "publish_date": "2023-04-20",
        "source_type": "公司项目披露",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_project_disclosure",
        "independence_key": "farasis_siro_turkiye",
        "independence_rationale": "孚能科技对土耳其合资工厂量产阶段和区域定位的原始披露。",
    },
    {
        "source_ref": "sunwoda_global_footprint",
        "source_url": "https://en.sunwoda.com/about",
        "title": "Sunwoda global manufacturing footprint",
        "title_zh": "欣旺达全球生产基地布局",
        "publisher": "Sunwoda",
        "publish_date": "2026-07-28",
        "source_type": "公司项目披露",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_project_disclosure",
        "independence_key": "sunwoda_global_manufacturing_footprint",
        "independence_rationale": "欣旺达官网对印度、越南、匈牙利、摩洛哥和泰国等生产基地的当前列表；不等同于各基地已形成有效产能。",
    },
    {
        "source_ref": "great_power_global_footprint",
        "source_url": "https://www.greatpower.net/en/about/",
        "title": "Great Power global footprint",
        "title_zh": "鹏辉能源全球业务与土耳其工厂布局",
        "publisher": "Great Power",
        "publish_date": "2026-07-28",
        "source_type": "公司项目披露",
        "quality_tier": 1,
        "source_channel": "web",
        "language": "en",
        "fetch_method": "web_fetch",
        "is_primary_source": True,
        "source_credibility": "company_project_disclosure",
        "independence_key": "great_power_global_footprint",
        "independence_rationale": "鹏辉能源官网对储能业务覆盖和土耳其工厂的当前披露；项目规模仍以公告和投产记录核验。",
    },
]

RECENT_RECONCILIATION_REPORTS: list[dict[str, Any]] = [
    {
        "source_ref": "calb_huatai_20260609",
        "source_file": (
            "papers/锂电池/中创新航/"
            "2026-06-09_华泰证券_中创新航_中创新航（03931）：穿越周期的头部电池厂.pdf"
        ),
        "title": "中创新航：穿越周期的头部电池厂",
        "publisher": "华泰证券",
        "publish_date": "2026-06-09",
        "source_type": "公司研报",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "recent_sell_side_financial_model",
        "independence_key": "huatai_calb_20260609",
        "independence_rationale": "最近两个季度内发布的公司模型，只在独立模型冻结后用于外部对账。",
    },
    {
        "source_ref": "eve_citi_20260609",
        "source_file": (
            "papers/锂电池/亿纬锂能/"
            "2026-06-09_citi_亿纬锂能_亿纬锂能（300014）：模型更新；目标价下调至87.9元_股.pdf"
        ),
        "title": "亿纬锂能：模型更新；目标价下调至87.9元/股",
        "publisher": "花旗研究",
        "publish_date": "2026-06-09",
        "source_type": "公司研报",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "recent_sell_side_financial_model",
        "independence_key": "citi_eve_20260609",
        "independence_rationale": "英文原始公司模型，与中文研报同级；只在独立模型冻结后用于外部对账。",
    },
    {
        "source_ref": "rept_clsa_20260511",
        "source_file": (
            "papers/锂电池/瑞浦兰钧/"
            "2026-05-11_clsa_瑞浦兰钧_瑞浦兰钧（00666）："
            "瑞浦兰钧;喜忧参半：上海论坛瑞浦兰钧会议要点.pdf"
        ),
        "title": "瑞浦兰钧：上海论坛会议要点",
        "publisher": "里昂证券",
        "publish_date": "2026-05-11",
        "source_type": "公司研报",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "en",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "recent_sell_side_financial_model",
        "independence_key": "clsa_rept_20260511",
        "independence_rationale": "英文原始公司研究，只在独立模型冻结后用于外部对账。",
    },
    {
        "source_ref": "sunwoda_zheshang_20260603",
        "source_file": (
            "papers/锂电池/欣旺达/"
            "2026-06-03_浙商证券_欣旺达_欣旺达（300207）："
            "点评报告：限制性股票与股票期权计划落地，开启成长新篇章.pdf"
        ),
        "title": "欣旺达：限制性股票与股票期权计划落地",
        "publisher": "浙商证券",
        "publish_date": "2026-06-03",
        "source_type": "公司研报",
        "quality_tier": 2,
        "source_channel": "report",
        "language": "zh",
        "fetch_method": "pdf_local",
        "is_primary_source": False,
        "source_credibility": "recent_sell_side_financial_model",
        "independence_key": "zheshang_sunwoda_20260603",
        "independence_rationale": "最近两个季度内发布的公司模型，只在独立模型冻结后用于外部对账。",
    },
]


COMPANY_REF = {
    "宁德时代": "catl",
    "比亚迪": "byd",
    "国轩高科": "gotion",
    "中创新航": "calb",
    "亿纬锂能": "eve",
    "瑞浦兰钧": "rept",
    "欣旺达": "sunwoda",
    "鹏辉能源": "great_power",
    "孚能科技": "farasis",
}


def _filing_sources() -> list[dict[str, Any]]:
    manifest = json.loads(FILING_MANIFEST.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for item in manifest["rows"]:
        company = str(item["company"])
        period = str(item["period"])
        suffix = period.lower().replace("2026", "26").replace("2025", "25")
        rows.append(
            {
                "source_ref": f"{COMPANY_REF[company]}_{suffix}",
                "source_file": str(item["local_path"]),
                "source_url": str(item["url"]),
                "title": str(item["title"]),
                "publisher": company,
                "publish_date": str(item["filename"])[:10],
                "source_type": "公告",
                "quality_tier": 1,
                "source_channel": "report",
                "language": "zh",
                "fetch_method": "pdf_local",
                "is_primary_source": True,
                "source_credibility": "listed_company_filing",
                "independence_key": f"{COMPANY_REF[company]}_{period}",
                "independence_rationale": "交易所或公司官网法定披露；镜像不另计独立证据。",
            }
        )
    return rows


SOURCE_SPECS: list[dict[str, Any]] = (
    WEB_SOURCES + RECENT_RECONCILIATION_REPORTS + _filing_sources()
)


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
    source = next(s for s in SOURCE_SPECS if s["source_ref"] == source_ref)
    return {
        "source_ref": source_ref,
        "company": company,
        "metric": metric,
        "period": period,
        "unit": unit,
        "value_num": float(value),
        "value_text": None,
        "source_excerpt": excerpt,
        "extraction_method": (
            "inferred"
            if inferred
            else "web_fetch"
            if source.get("source_channel") == "web"
            else "pdf_direct"
        ),
        "is_forecast": bool(forecast),
        "note": note,
        "scope_key": scope or metric,
    }


def _append_facts(
    rows: list[dict[str, Any]],
    source_ref: str,
    facts: list[tuple[str, str, str, float]],
    excerpt: str,
    *,
    company: str | None = None,
    scope: str,
) -> None:
    for period, metric, unit, value in facts:
        rows.append(
            _dp(
                source_ref,
                metric,
                period,
                unit,
                value,
                excerpt,
                company=company,
                scope=scope,
            )
        )


def build_data_points() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    sne_rank = [
        ("宁德时代", 188.4, 40.2),
        ("比亚迪", 67.6, 14.4),
        ("LG新能源", 41.0, 8.7),
        ("中创新航", 23.8, 5.1),
        ("国轩高科", 21.7, 4.6),
        ("SK On", 15.8, 3.4),
        ("松下", 15.1, 3.2),
        ("亿纬锂能", 15.4, 3.3),
        ("蜂巢能源", 12.1, 2.6),
        ("欣旺达", 11.4, 2.4),
    ]
    for company, volume, share in sne_rank:
        excerpt = (
            f"SNE Research统计2026年1—5月{company}全球动力电池装机"
            f"{volume:.1f}GWh、份额{share:.1f}%。"
        )
        rows.extend(
            [
                _dp(
                    "sne_global_ev_2026m5",
                    f"{company}全球动力电池装机",
                    "2026年1—5月",
                    "GWh",
                    volume,
                    excerpt,
                    company=company if company in COMPANY_REF else None,
                    scope="global_ev_battery_company_usage_2026m5",
                ),
                _dp(
                    "sne_global_ev_2026m5",
                    f"{company}全球动力电池份额",
                    "2026年1—5月",
                    "%",
                    share,
                    excerpt,
                    company=company if company in COMPANY_REF else None,
                    scope="global_ev_battery_company_share_2026m5",
                ),
            ]
        )
    _append_facts(
        rows,
        "sne_global_ev_2026m5",
        [
            ("2026年1—5月", "全球动力电池装机", "GWh", 469.2),
            ("2026年1—5月", "全球动力电池装机同比", "%", 16.3),
            ("2026年1—5月", "全球动力电池中国厂商前十数量", "家", 7),
            ("2026年1—5月", "全球动力电池中国厂商前十份额", "%", 72.6),
        ],
        "SNE Research统计2026年1—5月全球动力电池装机469.2GWh，同比增长16.3%；前十名中七家中国企业合计72.6%。",
        scope="global_ev_battery_market_2026m5",
    )
    for metric, value, formula in [
        ("全球动力电池CR3", 63.3, "CR3＝40.2%＋14.4%＋8.7%。"),
        ("全球动力电池CR5", 73.0, "CR5＝40.2%＋14.4%＋8.7%＋5.1%＋4.6%。"),
    ]:
        rows.append(
            _dp(
                "sne_global_ev_2026m5",
                metric,
                "2026年1—5月",
                "%",
                value,
                "按SNE Research同期前五家企业份额复算。",
                inferred=True,
                scope="global_ev_battery_concentration_2026m5",
                note=formula + " 分母为全球动力电池装机量，不是出货量或产能。",
            )
        )

    _append_facts(
        rows,
        "infolink_ess_2026q1",
        [
            ("2026Q1", "全球储能电芯出货", "GWh", 205.52),
            ("2026Q1", "全球储能电芯出货同比", "%", 98.70),
            ("2026Q1", "全球储能电芯出货环比", "%", 1.62),
            ("2026Q1", "全球储能电芯CR5", "%", 58.9),
            ("2026Q1", "全球储能电芯CR10", "%", 85.2),
            ("2026Q1", "全球大储电芯出货", "GWh", 178.27),
            ("2026Q1", "全球大储电芯出货同比", "%", 84.54),
            ("2026Q1", "全球小储电芯出货", "GWh", 27.25),
            ("2026Q1", "全球小储电芯出货同比", "%", 298.98),
            ("2026Q1", "500Ah以上电芯渗透率", "%", 5.0),
            ("2026全年预测", "500Ah以上电芯渗透率", "%", 20.0),
            ("2026Q1", "280Ah和314Ah小储电芯渗透率", "%", 22.0),
            ("2026Q2预测", "280Ah和314Ah小储电芯渗透率", "%", 30.0),
            ("2026全年预测", "全球储能电芯出货", "GWh", 897.0),
        ],
        "InfoLink估计2026年一季度全球储能电芯出货205.52GWh，CR5为58.9%、CR10为85.2%，并拆分大储和小储。",
        scope="global_ess_cell_market_2026q1",
    )

    _append_facts(
        rows,
        "china_gov_nev_2026h1",
        [
            ("2026H1", "中国新能源汽车产量", "万辆", 743.8),
            ("2026H1", "中国新能源汽车销量", "万辆", 744.6),
            ("2026H1", "中国纯电动车占新能源汽车销量", "%", 67.0),
        ],
        "中国汽车工业协会数据显示，2026年上半年新能源汽车产量743.8万辆、销量744.6万辆，纯电动车占新能源销量67%。",
        scope="china_nev_market_2026h1",
    )

    _append_facts(
        rows,
        "fastmarkets_cabia_2026h1",
        [
            ("2026H1", "中国动力与储能电池产量", "GWh", 1068.9),
            ("2026H1", "中国动力与储能电池产量同比", "%", 53.3),
            ("2026H1", "中国动力电池装车量", "GWh", 335.6),
            ("2026H1", "中国动力电池装车量同比", "%", 12.0),
            ("2026H1", "中国动力与储能电池销量", "GWh", 979.4),
            ("2026H1", "中国动力与储能电池销量同比", "%", 48.6),
            ("2026H1", "中国动力电池销量", "GWh", 661.3),
            ("2026H1", "中国动力电池销量同比", "%", 36.2),
            ("2026H1", "中国储能电池销量", "GWh", 318.1),
            ("2026H1", "中国储能电池销量同比", "%", 83.4),
            ("2026H1", "储能电池占中国电池销量", "%", 32.5),
            ("2026H1", "中国动力与储能电池出口", "GWh", 181.3),
            ("2026H1", "中国动力与储能电池出口同比", "%", 42.5),
            ("2026H1", "出口占中国电池销量", "%", 18.5),
            ("2026H1", "中国动力电池出口", "GWh", 122.7),
            ("2026H1", "中国动力电池出口同比", "%", 50.3),
            ("2026H1", "中国储能电池出口", "GWh", 58.6),
            ("2026H1", "中国储能电池出口同比", "%", 28.5),
            ("2026H1", "中国磷酸铁锂动力电池装车量", "GWh", 272.0),
            ("2026H1", "磷酸铁锂占中国动力装车", "%", 81.0),
            ("2026H1", "中国三元动力电池装车量", "GWh", 63.4),
            ("2026H1", "三元占中国动力装车", "%", 18.9),
            ("2026-06-26", "314Ah储能电芯报价下限", "元/Wh", 0.35),
            ("2026-06-26", "314Ah储能电芯报价上限", "元/Wh", 0.40),
        ],
        "Fastmarkets转引中国汽车动力电池产业创新联盟统计，并记录其314Ah储能电芯报价区间。",
        scope="china_power_ess_battery_2026h1",
    )
    _append_facts(
        rows,
        "askci_china_ev_2026h1",
        [
            ("2026H1", "中国动力电池企业CR3", "%", 69.37),
            ("2026H1", "中国动力电池企业CR5", "%", 80.56),
            ("2026H1", "中国动力电池企业CR10", "%", 93.90),
        ],
        "按中国汽车动力电池产业创新联盟装车排名汇总，2026年上半年中国动力电池CR3、CR5和CR10分别为69.37%、80.56%和93.90%。",
        scope="china_ev_battery_concentration_2026h1",
    )
    _append_facts(
        rows,
        "ess_news_314ah_price_202604",
        [
            ("2025-10下旬", "中国314Ah储能电芯价格", "元/Wh", 0.300),
            ("2026-04-20", "中国314Ah储能电芯价格", "元/Wh", 0.365),
        ],
        "ESS News记录中国314Ah储能电芯价格由2025年10月下旬约0.300元/Wh升至2026年4月20日约0.365元/Wh。",
        scope="china_314ah_storage_cell_price",
    )

    _append_facts(
        rows,
        "cn_consumption_tax_2026",
        [
            ("2026-09-01起", "中国锂离子电池消费税率", "%", 2.0),
            ("2027-09-01起", "中国锂离子电池消费税率", "%", 4.0),
            ("2026全年等效", "中国锂离子电池消费税率", "%", 0.66666667),
            ("2027全年等效", "中国锂离子电池消费税率", "%", 2.66666667),
            ("2026-09至2028-12", "钠离子电池消费税率", "%", 0.0),
            ("2026-09至2028-12", "固态电池消费税率", "%", 0.0),
            ("2026-09至2028-12", "燃料电池消费税率", "%", 0.0),
        ],
        "2026年第20号公告规定锂离子电池分阶段按2%和4%征税，并对符合标准的钠离子、固态和燃料电池阶段性免税。",
        scope="cn_battery_consumption_tax",
    )
    _append_facts(
        rows,
        "cn_export_rebate_2026",
        [
            ("2026-04-01至12-31", "中国电池出口退税率", "%", 6.0),
            ("2027-01-01起", "中国电池出口退税率", "%", 0.0),
            ("2026全年等效", "中国电池出口退税减少率", "%", 2.25),
            ("2027全年", "中国电池出口退税减少率", "%", 9.0),
        ],
        "财政部公告规定电池出口退税率2026年4月起由9%降至6%，2027年起取消。",
        scope="cn_battery_export_rebate",
    )
    _append_facts(
        rows,
        "irs_clean_vehicle_credit",
        [("2025-09-30后", "美国联邦清洁车辆抵免适用比例", "%", 0.0)],
        "美国国税局说明，30D、25E和45W不再适用于2025年9月30日以后取得的车辆。",
        scope="us_clean_vehicle_credit",
    )
    _append_facts(
        rows,
        "ustr_battery_tariff",
        [
            ("2024起", "美国中国电动车锂电池301关税率", "%", 25.0),
            ("2026起", "美国中国非电动车锂电池301关税率", "%", 25.0),
        ],
        "美国贸易代表办公室公布中国电动车电池自2024年、非电动车锂电池自2026年适用25%关税。",
        scope="us_section301_battery_tariff",
    )
    _append_facts(
        rows,
        "irs_45x_final",
        [
            ("当前", "美国45X电芯抵免", "美元/kWh", 35.0),
            ("当前", "美国45X含电芯模组抵免", "美元/kWh", 10.0),
            ("当前", "美国45X不含电芯模组抵免", "美元/kWh", 45.0),
            ("2030", "美国45X抵免保留比例", "%", 75.0),
            ("2031", "美国45X抵免保留比例", "%", 50.0),
            ("2032", "美国45X抵免保留比例", "%", 25.0),
        ],
        "美国国税局45X最终规则明确电芯、模组抵免金额及2030—2032退坡。",
        scope="us_section45x_battery_credit",
    )
    _append_facts(
        rows,
        "eu_battery_regulation",
        [("2027-02-18起", "欧盟电池护照适用门槛", "kWh", 2.0)],
        "欧盟电池法规要求相关电动车、轻型交通工具及2kWh以上工业电池自2027年2月18日起配置电池护照。",
        scope="eu_battery_passport",
    )
    _append_facts(
        rows,
        "eu_due_diligence_delay",
        [("2027-08-18起", "欧盟电池尽职调查生效状态", "布尔值", 1.0)],
        "欧盟理事会通过延期安排，将电池尽职调查义务推迟至2027年8月18日。",
        scope="eu_battery_due_diligence",
    )
    _append_facts(
        rows,
        "eu_battery_booster",
        [
            ("2026计划", "欧盟Battery Booster总规模", "亿欧元", 15.0),
            ("单项目", "欧盟Battery Booster贷款上限", "亿欧元", 5.0),
            ("项目资格", "欧盟Battery Booster最低产能", "GWh", 10.0),
            ("贷款条款", "欧盟Battery Booster名义利率", "%", 0.0),
        ],
        "欧盟委员会Battery Booster计划总规模15亿欧元、单项目最高5亿欧元无息贷款，适用项目最低10GWh。",
        scope="eu_battery_booster",
    )
    _append_facts(
        rows,
        "eu_bev_duties",
        [
            ("当前", "欧盟中国纯电动车反补贴税率下限", "%", 7.8),
            ("当前", "欧盟中国纯电动车反补贴税率上限", "%", 35.3),
        ],
        "欧盟委员会公布中国生产纯电动车的企业差异化最终反补贴税率为7.8%—35.3%。",
        scope="eu_china_bev_duties",
    )
    _append_facts(
        rows,
        "iea_ev_batteries_2026",
        [
            ("2025", "全球锂离子电池需求下限", "TWh", 1.5),
            ("2025", "全球锂离子电池需求同比增速下限", "%", 35.0),
            ("2025", "全球电动车电池部署", "TWh", 1.2),
            ("2025", "电动车占全球锂离子电池部署比例下限", "%", 70.0),
            ("2025", "轻型车占全球电动车电池部署比例下限", "%", 85.0),
            ("2025", "电动卡车占全球电动车电池部署比例约值", "%", 8.0),
            ("2030 CPS与STEPS预测", "全球电动车电池部署约值", "TWh", 3.0),
            ("2035 CPS预测", "全球电动车电池部署约值", "TWh", 4.0),
            ("2035 STEPS预测", "全球电动车电池部署约值", "TWh", 5.0),
            ("2025年末", "全球锂离子电池名义产能下限", "TWh", 4.0),
            ("2025年末", "中国全球电池名义产能占比下限", "%", 80.0),
            ("2025", "中国全球电池产量占比下限", "%", 80.0),
            ("2025", "中国厂商全球电动车电池装机份额约值", "%", 75.0),
            ("2025", "中国全球电动车电池部署占比约值", "%", 60.0),
            ("2025", "欧盟全球电动车电池部署占比约值", "%", 15.0),
            ("2025", "美国全球电动车电池部署占比约值", "%", 10.0),
            ("2025", "中国电池包相对北美价格折价约值", "%", 30.0),
            ("2025", "中国电池包相对欧洲价格折价约值", "%", 35.0),
            ("2025", "磷酸铁锂电池包相对三元价格折价下限", "%", 40.0),
            ("2025", "中国全球电池回收产能占比下限", "%", 85.0),
            ("2025", "三元正极活性材料占电芯生产成本", "%", 45.0),
            ("2025", "磷酸铁锂正极活性材料占电芯生产成本", "%", 27.5),
            ("成熟量产要求", "新电池工厂良率要求下限", "%", 90.0),
            ("典型爬坡", "新电池工厂接近名义产能所需时间下限", "年", 5.0),
        ],
        "IEA《全球电动汽车展望2026》指出，2025年全球电池需求超过1.5TWh，其中电动车电池部署1.2TWh；2030年电动车电池部署在当前政策和既定政策情景下均接近3TWh。全球名义产能超过4TWh，中国占全球电芯产能和产量八成以上。",
        scope="iea_global_battery_market_2025",
    )
    _append_facts(
        rows,
        "iea_ev_summary_2026",
        [
            ("2025", "全球电动汽车销量下限", "万辆", 2000.0),
            ("2025", "全球电动汽车销量渗透率约值", "%", 25.0),
            ("2026预测", "全球电动汽车销量", "万辆", 2300.0),
            ("2026预测", "全球电动汽车销量渗透率", "%", 28.0),
            ("2025", "欧洲电动汽车销量同比增速下限", "%", 30.0),
            ("2025", "中国电动汽车销量渗透率约值", "%", 55.0),
            ("2025", "美国电动汽车销量渗透率上限", "%", 10.0),
            ("2025", "东南亚电动汽车销量同比增速下限", "%", 100.0),
            ("2025", "拉丁美洲电动汽车销量同比增速", "%", 75.0),
        ],
        "IEA预计2026年全球电动汽车销量约2300万辆、渗透率28%；2025年中国、欧洲、美国和新兴市场的增速与渗透率明显分化。",
        scope="iea_global_ev_demand_2025_2026",
    )
    _append_facts(
        rows,
        "iea_ev_manufacturing_2026",
        [
            ("2030预测", "美国电池产量上限", "GWh", 350.0),
            ("2035预测", "美国电池产量约占已承诺名义产能", "%", 40.0),
            ("2025", "中国电动车产量全球份额", "%", 70.0),
            ("2025", "中国正极活性材料产量全球份额约值", "%", 85.0),
            ("2025", "中国负极活性材料产量全球份额下限", "%", 90.0),
        ],
        "IEA制造与贸易模型显示，美国已承诺电池项目面对需求下修和较低利用率风险；中国仍控制大部分正负极材料与电芯制造。",
        scope="iea_battery_manufacturing_trade_2026",
    )
    _append_facts(
        rows,
        "iea_critical_minerals_2026",
        [
            ("2025", "关键矿产最大精炼国平均份额", "%", 72.0),
            ("2025", "电池材料公司资本开支同比", "%", -20.0),
            ("2025", "锂矿公司资本开支同比", "%", -40.0),
            ("2025至2026-04", "钴价格累计涨幅约值", "%", 130.0),
            ("2025", "中国石墨等部分材料精炼份额下限", "%", 90.0),
            ("2025", "石墨全面中断影响境外下游产值下限", "亿美元", 3000.0),
            ("2040 STEPS", "全球锂需求相对当前倍数下限", "倍", 3.0),
            ("2035基准", "全球钴供给缺口占需求下限", "%", 25.0),
        ],
        "IEA《全球关键矿产展望2026》显示精炼集中度继续上升，电池材料投资下降，钴出口配额和中国电池材料出口管制已把供应链集中风险转为实际政策风险。",
        scope="iea_battery_material_geopolitics_2026",
    )
    _append_facts(
        rows,
        "cn_battery_export_control_2025",
        [
            ("2025-11-08起", "中国受管制锂离子电池重量能量密度门槛", "Wh/kg", 300.0),
            ("2025-11-08起", "中国受管制磷酸铁锂材料压实密度门槛", "g/cm³", 2.5),
            ("2025-11-08起", "中国受管制磷酸铁锂材料克容量门槛", "mAh/g", 156.0),
        ],
        "商务部和海关总署公告对达到参数门槛的锂离子电池、关键设备、正极材料、石墨负极材料及相关技术实施出口许可；它不是对全部锂电池的一刀切禁运。",
        scope="cn_battery_material_equipment_export_control",
    )
    _append_facts(
        rows,
        "cn_storage_capacity_price_2026",
        [("2026政策", "中国电网侧独立新型储能可纳入容量电价", "布尔值", 1.0)],
        "国家发展改革委和国家能源局明确，对符合条件的电网侧独立新型储能可按顶峰能力和放电时长折算容量电价，并在现货市场连续运行后衔接可靠容量补偿。",
        scope="cn_independent_storage_capacity_price",
    )
    _append_facts(
        rows,
        "cn_battery_recycling_2026",
        [("2026-04-01起", "中国动力电池回收新规实施状态", "布尔值", 1.0)],
        "六部门动力电池回收新规自2026年4月1日起施行，强化生产企业、整车企业、维修和回收主体的责任与信息链。",
        scope="cn_ev_battery_recycling_regulation",
    )
    _append_facts(
        rows,
        "eu_battery_passport_2026",
        [
            ("2026-07-20", "欧盟电池产品护照登记系统运行状态", "布尔值", 1.0),
            ("2027-02-18起", "欧盟相关电池数字产品护照强制状态", "布尔值", 1.0),
        ],
        "欧盟委员会实施页说明，DPP登记系统计划于2026年7月运行，相关电动车、轻型交通和工业电池自2027年2月18日起强制配置电池护照。",
        scope="eu_battery_dpp_implementation",
    )
    _append_facts(
        rows,
        "eu_industrial_accelerator_2026",
        [
            ("2026提案", "欧盟战略行业外资审查投资门槛", "亿欧元", 1.0),
            ("2026提案", "欧盟战略外资来源国全球产能份额门槛", "%", 40.0),
            ("2026提案", "欧盟战略外资欧盟员工比例要求", "%", 50.0),
        ],
        "欧盟委员会2026年3月提案拟对电池等战略行业的大型第三国外资附加本地就业、技术转移和本地含量条件；该提案尚未完成立法，不能作为现行义务。",
        scope="eu_industrial_accelerator_proposal",
    )
    _append_facts(
        rows,
        "india_acc_pli_2026",
        [
            ("计划总目标", "印度ACC电池生产激励目标产能", "GWh", 50.0),
            ("截至2026-02", "印度ACC电池生产激励已分配产能", "GWh", 40.0),
            ("计划总额", "印度ACC电池生产激励预算", "亿印度卢比", 1810.0),
        ],
        "印度重工业部披露ACC电池生产激励计划目标50GWh，已向四家受益企业分配40GWh，预算1810亿印度卢比。",
        scope="india_acc_battery_pli",
    )
    _append_facts(
        rows,
        "afdb_gotion_morocco_2026",
        [
            ("2026-07", "非洲开发银行国轩摩洛哥项目贷款", "亿欧元", 1.0),
            ("2026-07", "国轩摩洛哥项目拟追加融资", "亿欧元", 1.41),
            ("一期", "国轩摩洛哥电芯与电池包产能", "GWh", 10.0),
            ("长期规划", "国轩摩洛哥电芯与电池包产能", "GWh", 100.0),
        ],
        "非洲开发银行批准1亿欧元贷款，并拟组织1.41亿欧元追加融资；新闻稿口径的一期为10GWh、长期规划100GWh，需与项目环境文件的20GWh口径继续对账。",
        scope="gotion_morocco_project_financing",
    )
    _append_facts(
        rows,
        "portugal_calb_sines_2025",
        [
            ("项目计划", "中创新航葡萄牙Sines工厂投资额", "亿欧元", 20.0),
            ("项目计划", "中创新航葡萄牙Sines工厂产能", "GWh", 15.0),
            ("项目计划", "中创新航葡萄牙Sines工厂直接就业", "人", 1800.0),
            ("项目计划", "中创新航葡萄牙Sines工厂全面运营目标年", "年", 2028.0),
        ],
        "葡萄牙政府披露中创新航Sines项目投资约20亿欧元、产能15GWh、直接就业1800人并计划2028年全面运营；计划值不等于已投产有效产能。",
        scope="calb_portugal_sines_project",
    )
    _append_facts(
        rows,
        "gotion_michigan_case_2026",
        [
            ("原计划", "国轩密歇根项目计划投资", "亿美元", 23.64),
            ("原计划", "国轩密歇根项目计划就业", "人", 2350.0),
            ("2025违约争议", "国轩密歇根项目州资金返还争议约值", "亿美元", 0.237),
        ],
        "美国第六巡回上诉法院判决记录，密歇根州在2025年认定项目连续120日未发生合资格活动并要求返还近2400万美元；该案例证明地方政治、诉讼和补贴合同可先于技术与客户改变项目现金流。",
        scope="gotion_michigan_project_case",
    )
    _append_facts(
        rows,
        "eve_malaysia_factory",
        [("一期计划", "亿纬锂能马来西亚圆柱电池项目投资上限", "亿美元", 4.223)],
        "亿纬锂能官网披露马来西亚一期圆柱电池项目投资不超过4.223亿美元，并另行规划储能工厂用地。",
        scope="eve_malaysia_factory",
    )

    regional = [
        ("宁德时代", "catl_25a", 30.60, 69.40),
        ("比亚迪", "byd_25a", 38.65, 61.35),
        ("国轩高科", "gotion_25a", 22.59, 77.41),
        ("中创新航", "calb_25a", 2.10, 97.90),
        ("亿纬锂能", "eve_25a", 23.56, 76.44),
        ("瑞浦兰钧", "rept_25a", 5.87, 94.13),
        ("欣旺达", "sunwoda_25a", 38.64, 61.36),
        ("鹏辉能源", "great_power_25a", 15.01, 84.99),
        ("孚能科技", "farasis_25a", 81.88, 18.12),
    ]
    for company, source, overseas, domestic in regional:
        scope_note = (
            "比亚迪和欣旺达为集团地区收入，不能直接视作电池出口；"
            "孚能科技为主营电池业务地区收入；其他公司按年报分地区口径。"
        )
        excerpt = (
            f"{company}2025年披露口径下境外收入占{overseas:.2f}%、"
            f"境内收入占{domestic:.2f}%。"
        )
        rows.extend(
            [
                _dp(
                    source,
                    f"{company}境外收入占比",
                    "2025",
                    "%",
                    overseas,
                    excerpt,
                    company=company,
                    scope="company_reported_geographic_revenue_share_2025",
                    note=scope_note,
                ),
                _dp(
                    source,
                    f"{company}境内收入占比",
                    "2025",
                    "%",
                    domestic,
                    excerpt,
                    company=company,
                    scope="company_reported_geographic_revenue_share_2025",
                    note=scope_note,
                ),
            ]
        )

    company_facts: list[
        tuple[str, str, list[tuple[str, str, str, float]], str]
    ] = [
        (
            "宁德时代",
            "catl_25a",
            [
                ("2025", "锂离子电池销量", "GWh", 661),
                ("2025", "动力电池销量", "GWh", 541),
                ("2025", "储能电池销量", "GWh", 121),
                ("2025年末", "电池系统产能", "GWh", 772),
                ("2025年末", "电池系统在建产能", "GWh", 321),
                ("2025", "电池系统产能利用率", "%", 96.9),
                ("2025", "电池系统产量", "GWh", 748),
                ("2025年末", "电池系统库存量", "GWh", 186),
            ],
            "宁德时代2025年报披露销量、分业务销量、产能、在建产能、利用率、产量和库存。",
        ),
        (
            "比亚迪",
            "byd_25a",
            [("2025", "全球储能系统出货量下限", "GWh", 60)],
            "比亚迪2025年报披露全球储能系统出货量超过60GWh；数据点保守记为下限60GWh。",
        ),
        (
            "国轩高科",
            "gotion_25a",
            [
                ("2025", "全球动力电池装机", "GWh", 53.5),
                ("2025", "全球动力电池装机同比", "%", 82.5),
                ("2025", "全球动力电池份额", "%", 4.5),
                ("2025", "中国动力电池装机", "GWh", 43.44),
                ("2025", "中国动力电池份额", "%", 5.65),
                ("2025", "储能电池出货量下限", "GWh", 30.0),
                ("2025", "全球储能电池份额", "%", 5.0),
                ("2025", "全球基站与数据中心备电电池份额", "%", 28.0),
            ],
            "国轩高科2025年报披露动力电池装机、份额及储能出货和备电细分份额。",
        ),
        (
            "中创新航",
            "calb_25a",
            [
                ("2025", "全球动力电池装机排名", "名", 4),
                ("2025", "中国动力电池装机排名", "名", 3),
                ("2025", "全球储能电芯出货排名", "名", 4),
            ],
            "中创新航2025年报披露动力电池全球第四、中国第三，储能电芯全球第四。",
        ),
        (
            "亿纬锂能",
            "eve_25a",
            [
                ("2025", "动力电池出货", "GWh", 50.15),
                ("2025", "动力电池出货同比", "%", 65.56),
                ("2025", "储能电池出货", "GWh", 71.05),
                ("2025", "储能电池出货同比", "%", 40.84),
            ],
            "亿纬锂能2025年报披露动力和储能电池出货量及同比。",
        ),
        (
            "瑞浦兰钧",
            "rept_25a",
            [
                ("2025", "锂电池产品销量", "GWh", 82.7),
                ("2025", "锂电池产品销量同比", "%", 89.2),
                ("2025年末", "设计产能", "GWh", 90.0),
                ("2025", "问顶电池月度出货量下限", "GWh", 2.0),
                ("印尼一期规划", "印尼动力与储能电池规划产能", "GWh", 8.0),
            ],
            "瑞浦兰钧2025年报披露销量、设计产能、问顶产品月度出货与印尼一期规划。",
        ),
        (
            "欣旺达",
            "sunwoda_25a",
            [
                ("2025", "电动汽车类电池出货量", "GWh", 42.72),
                ("2025", "电动汽车类电池出货同比", "%", 68.92),
                ("2025", "储能系统装机量", "GWh", 25.6),
                ("2025", "储能系统装机量同比", "%", 188.0),
                ("2025", "家储和工商储海外覆盖国家数量下限", "个", 30.0),
            ],
            "欣旺达2025年报披露电动汽车类电池出货、储能系统装机及海外覆盖。",
        ),
        (
            "鹏辉能源",
            "great_power_25a",
            [
                ("2025", "全球储能电芯出货排名", "名", 9.0),
                ("2025年末", "连续入选BNEF Tier1季度数", "个季度", 7.0),
            ],
            "鹏辉能源2025年报披露储能电芯全球前九，并连续七个季度入选BNEF Tier1。",
        ),
        (
            "孚能科技",
            "farasis_25a",
            [
                ("2025年末", "土耳其Siro已爬坡产能", "GWh", 6.0),
                ("2025年末", "赣州一期规划产能", "GWh", 30.0),
                ("2025年末", "广州一期规划产能", "GWh", 30.0),
                ("2025", "中国动力电池出口销量排名", "名", 4.0),
            ],
            "孚能科技2025年报披露土耳其Siro 6GWh已爬坡，赣州和广州一期项目投产，并称出口销量全国第四。",
        ),
    ]
    for company, source, facts, excerpt in company_facts:
        _append_facts(
            rows,
            source,
            facts,
            excerpt,
            company=company,
            scope=f"{COMPANY_REF[company]}_operating_facts_2025",
        )

    return rows


KEY_ARGUMENTS = [
    {
        "argument": "需求高增长与名义产能过剩可以同时成立",
        "evidence": [
            "iea_ev_batteries_2026",
            "infolink_ess_2026q1",
            "fastmarkets_cabia_2026h1",
        ],
        "conclusion": (
            "2025年全球电动车电池部署1.2TWh、2030年接近3TWh，"
            "但2025年末名义产能已超过4TWh；供需判断必须从名义产能折算"
            "到投产、认证、利用率、良率、产品和区域资格后的有效供给。"
        ),
    },
    {
        "argument": "动力与储能是两个分母、两套排名",
        "evidence": [
            "sne_global_ev_2026m5",
            "infolink_ess_2026q1",
            "fastmarkets_cabia_2026h1",
        ],
        "conclusion": "全球动力电池CR5约73.0%，储能电芯CR5约58.9%；动力更集中，但储能CR10仍高达85.2%，不能用一个“电池市占率”替代。",
    },
    {
        "argument": "行业增长已从单一新能源汽车扩展为动力、储能和出口三条需求线",
        "evidence": [
            "china_gov_nev_2026h1",
            "fastmarkets_cabia_2026h1",
            "infolink_ess_2026q1",
        ],
        "conclusion": "2026年上半年中国储能电池销量同比83.4%，快于动力36.2%；出口占总销量18.5%，政策和海外订单已能明显改变利润。",
    },
    {
        "argument": "名义产能不是有效供给",
        "evidence": [
            "catl_25a",
            "rept_25a",
            "farasis_25a",
            "calb_25a",
        ],
        "conclusion": "有效供给需要客户认证、产品结构、利用率、良率和区域合规同时成立；宁德时代96.9%的利用率不能外推到爬坡中的海外或新基地。",
    },
    {
        "argument": "税负和贸易政策必须按收入暴露与承担比例传导",
        "evidence": [
            "cn_consumption_tax_2026",
            "cn_export_rebate_2026",
            "ustr_battery_tariff",
            "irs_45x_final",
            "eu_battery_regulation",
        ],
        "conclusion": "集团海外收入不是出口退税清单收入或美国直供收入；45X和欧盟无息贷款在资格、获批和爬坡前不能计入基准利润。",
    },
    {
        "argument": "政策与地缘风险已经从关税扩展到需求、资格、技术、材料和项目现金流",
        "evidence": [
            "irs_clean_vehicle_credit",
            "irs_pfe_2026",
            "eu_battery_passport_2026",
            "eu_industrial_accelerator_2026",
            "cn_battery_export_control_2025",
            "iea_critical_minerals_2026",
        ],
        "conclusion": (
            "美国需求与制造补贴方向分化，欧盟强调可追溯本地化，中国对"
            "部分电池、材料、设备和技术实施出口许可，关键矿产集中度继续"
            "上升；公司影响必须逐地区、逐项目和逐供应链节点计算。"
        ),
    },
]
