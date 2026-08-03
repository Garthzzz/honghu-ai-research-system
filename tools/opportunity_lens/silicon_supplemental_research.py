from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence


AS_OF_DATE = "2026-07-19"


DEMAND_SUPPLEMENTAL_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "DMD-SEMI-MEMORY-20260629",
        "title": "SEMI Projects 300mm Memory Equipment Investment to Surpass $50 Billion in 2026",
        "title_zh": "SEMI预计2026年300毫米存储设备投资首次超过500亿美元",
        "publisher": "SEMI",
        "published_date": "2026-06-29",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_web",
        "url": "https://www.semi.org/en/taxonomy/term/46781",
        "local_locator": None,
        "local_location_detail": "页面内标题：SEMI Projects 300mm Memory Equipment Investment to Surpass $50 Billion in 2026",
        "excerpt": (
            "Worldwide 300mm memory capacity is projected to increase, reaching 4.1 million "
            "wafers per month in 2026 and 4.2 million wafers per month in 2027."
        ),
        "excerpt_zh": "全球300毫米存储产能预计在2026年达到每月410万片，2027年达到每月420万片。",
        "independence_key": "SEMI_300MM_MEMORY_2Q26",
        "independence_rationale": "SEMI 2026年第二季度300毫米晶圆厂展望的同一次公开发布，按一个独立证据组计。",
        "temporal_warning": None,
        "fact_count": 2,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-SEMI-WAFER-OUTLOOK-202509",
        "title": "SEMI Market Outlook: Silicon Wafer Shipment Trends",
        "title_zh": "SEMI市场展望：半导体硅片出货趋势",
        "publisher": "SEMI",
        "published_date": "2025-09",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_pdf",
        "url": "https://www.semi.org/sites/semi.org/files/2025-09/5%20Clark%20Tseng_Building%20the%20Future-AI%20Investment%2C%20Equipment%20%26%20Materials%20Market%20Outlook.pdf",
        "local_locator": None,
        "local_location_detail": "第25页，Silicon Wafer Shipment Trends",
        "excerpt": (
            "The 300mm wafer segment is projected to reach new highs by 2028, exceeding "
            "10,800 MSI; the 200mm segment is expected to stabilize around 2,500-2,700 MSI through 2028."
        ),
        "excerpt_zh": "300毫米硅片出货预计到2028年创历史新高并超过10,800百万平方英寸；200毫米预计稳定在2,500—2,700百万平方英寸。",
        "independence_key": "SEMI_WAFER_OUTLOOK_202509",
        "independence_rationale": "SEMI市场展望中的硅片出货预测，独立于单家公司扩产公告。",
        "temporal_warning": None,
        "fact_count": 2,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-SEMI-SI-MONITOR-2026Q1",
        "title": "Silicon Wafer Market Monitor Q1 2026",
        "title_zh": "SEMI硅片市场监测报告2026年第一季度版",
        "publisher": "SEMI",
        "published_date": "2026-Q1",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_web",
        "url": "https://www.semi.org/en/products-services/market-data/si-wafer-monitor",
        "local_locator": None,
        "local_location_detail": "公开产品说明；完整供需数据需订阅",
        "excerpt": (
            "The report provides quarterly silicon wafer shipment data by region and wafer size, "
            "and covers supply/demand dynamics and silicon wafer pricing trends and forecasts."
        ),
        "excerpt_zh": "该付费报告按地区和尺寸提供季度硅片出货，并覆盖供需动态、硅片价格趋势和预测；公开产品页不披露完整数表。",
        "independence_key": "SEMI_SI_WAFER_MONITOR_2026Q1",
        "independence_rationale": "SEMI对其当前硅片供需数据库范围与公开可得边界的官方说明。",
        "temporal_warning": None,
        "fact_count": 1,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-NIST-GLOBALWAFERS",
        "title": "GlobalWafers Texas CHIPS Award",
        "title_zh": "美国CHIPS项目：环球晶圆得州和密苏里项目",
        "publisher": "NIST / CHIPS for America",
        "published_date": "2026",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_web",
        "url": "https://www.nist.gov/chips/globalwafers-texas-sherman",
        "local_locator": None,
        "local_location_detail": "Economic and National Security Impact；Project Overview",
        "excerpt": (
            "Approximately 90% of silicon wafers are sourced from East Asia today, with five "
            "corporations managing the majority of global supply. Expected capital expenditure "
            "for the GlobalWafers projects is $4 billion."
        ),
        "excerpt_zh": "目前约90%的硅片来自东亚，全球供应主要由五家公司掌握；环球晶圆美国项目预计资本支出40亿美元。",
        "independence_key": "NIST_GLOBALWAFERS_FINAL_AWARD",
        "independence_rationale": "美国政府最终激励项目页，独立于发行人披露。",
        "temporal_warning": None,
        "fact_count": 3,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-UMC-FAB12I-CURRENT",
        "title": "UMC Fab Information",
        "title_zh": "联电晶圆厂信息：新加坡Fab 12i为12英寸厂",
        "publisher": "UMC",
        "published_date": "2026",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "zh",
        "source_type": "official_web",
        "url": "https://www.umc.com/zh-CN/Html/fab_information",
        "local_locator": None,
        "local_location_detail": "12英寸晶圆厂列表中的Fab 12i",
        "excerpt": "联电的第二座12英寸晶圆厂Fab 12i位于新加坡，是专门技术中心。",
        "excerpt_zh": "联电的第二座12英寸晶圆厂Fab 12i位于新加坡，是专门技术中心。",
        "independence_key": "UMC_FAB_INFORMATION_CURRENT",
        "independence_rationale": "联电当前晶圆厂信息页，用于补充项目公告未重复写出的尺寸。",
        "temporal_warning": None,
        "fact_count": 1,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-NANYA-FAB5A-12INCH",
        "title": "Nanya New Fab Plan",
        "title_zh": "南亚科技Fab 5A新厂规划",
        "publisher": "Nanya Technology",
        "published_date": "2022-07-11",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_pdf",
        "url": "https://www.nanya.com/en/Activity?Action=IR_investorcalendar_FileName&Id=206&column=Presentation",
        "local_locator": None,
        "local_location_detail": "投资者资料第13页，New FAB Plan",
        "excerpt": (
            "12-inch DRAM FAB; the investment plan will take three phases; approximately "
            "45,000 wafers per month after three phases."
        ),
        "excerpt_zh": "该项目为12英寸DRAM厂，分三期实施，三期完成后约每月4.5万片。",
        "independence_key": "NANYA_FAB5A_PLAN_2022",
        "independence_rationale": "南亚科技同一项目的投资者资料；仅用于确认设计尺寸与历史规划，不证明当前爬坡。",
        "temporal_warning": "严重时效提醒：这是2022年项目规划，只能证明当时设计尺寸和规模，不能单独证明2026年的实际产能。",
        "fact_count": 2,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-SAMSUNG-TAYLOR-20260610",
        "title": "Samsung Austin Semiconductor 2025 Economic Impact",
        "title_zh": "三星奥斯汀半导体2025年经济影响及Taylor进度",
        "publisher": "Samsung Semiconductor",
        "published_date": "2026-06-10",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_web",
        "url": "https://semiconductor.samsung.com/sas/local-news/samsung-austin-semiconductors-two-campuses-inject-10-9b-into-central-texas-economy-in-2025/",
        "local_locator": None,
        "local_location_detail": "页面末段Taylor 2026目标",
        "excerpt": (
            "In 2026, the company aims to establish the Taylor fab, utilizing EUV technology "
            "to produce 2nm chips in the U.S. The site is expected to be operational by the end of 2026."
        ),
        "excerpt_zh": "三星计划在2026年建成Taylor工厂，使用EUV在美国生产2纳米芯片，目标在2026年底前投入运营。",
        "independence_key": "SAMSUNG_TAYLOR_UPDATE_20260610",
        "independence_rationale": "三星2026年当前项目进度披露，替代早期时间表。",
        "temporal_warning": None,
        "fact_count": 2,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-SONY-KOSHI-20260514",
        "title": "Sony Group Corporate Strategy 2026",
        "title_zh": "索尼集团2026年经营战略：熊本合志新厂合作研究",
        "publisher": "Sony Group",
        "published_date": "2026-05-14",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_web",
        "url": "https://www.sony.com/en/SonyInfo/News/Press/202605/26-012E/",
        "local_locator": None,
        "local_location_detail": "半导体影像传感器战略合作段落",
        "excerpt": (
            "Sony and TSMC signed a non-binding memorandum of understanding and are studying "
            "development and production lines utilizing Sony's newly constructed fab in Koshi City, Kumamoto Prefecture."
        ),
        "excerpt_zh": "索尼与台积电签署无约束力谅解备忘录，研究利用索尼在熊本县合志市新建工厂设置下一代图像传感器开发和生产线。",
        "independence_key": "SONY_TSMC_KOSHI_MOU_202605",
        "independence_rationale": "索尼当前战略发布；合作仍为研究阶段，不能视为已确定量产。",
        "temporal_warning": None,
        "fact_count": 2,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-SILTRONIC-AR2025",
        "title": "Siltronic Annual Report 2025",
        "title_zh": "世创2025年年度报告",
        "publisher": "Siltronic AG",
        "published_date": "2026-03-12",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_pdf",
        "url": "https://www.siltronic.com/fileadmin/investorrelations/2025/Q4/260312_Siltronic_Annual_Report_2025_safe.pdf",
        "local_locator": None,
        "local_location_detail": "第5—7页，市场环境、新加坡300毫米厂认证与爬坡",
        "excerpt": (
            "We were able to complete many important customer qualifications over the past twelve months. "
            "We are adjusting the production ramp carefully in line with current market developments. "
            "Since demand remains below our original expectations, capacity expansion is proceeding at a reduced pace."
        ),
        "excerpt_zh": "过去十二个月完成了多项重要客户认证；公司根据市场变化审慎调整新加坡工厂爬坡，因为需求低于原先预期，扩产正以较慢速度推进。",
        "independence_key": "SILTRONIC_ANNUAL_REPORT_2025",
        "independence_rationale": "世创2025年年报对新加坡300毫米厂当前认证和爬坡状态的发行人披露。",
        "temporal_warning": None,
        "fact_count": 3,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-SEMI-300MM-OUTLOOK-2Q26",
        "title": "300mm Fab Outlook (2Q 2026 Update)",
        "title_zh": "SEMI 300毫米晶圆厂展望2026年第二季度更新",
        "publisher": "SEMI",
        "published_date": "2026-06",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_web",
        "url": "https://www.semi.org/en/products-services/market-data/300mm-fab-outlook",
        "local_locator": None,
        "local_location_detail": "Key Message与Report Highlights",
        "excerpt": (
            "Global 300mm front-end equipment spending is expected to reach a new record of US$142 billion "
            "in 2026. Total installed 300mm capacity is projected to increase by 7% in 2026 and continue "
            "to grow at an approximate 7% rate from 2027 to 2029."
        ),
        "excerpt_zh": "全球300毫米前道设备支出预计2026年达到1,420亿美元；300毫米装机产能预计2026年增长7%，2027—2029年继续以约7%的速度增长。",
        "independence_key": "SEMI_300MM_FAB_OUTLOOK_2Q26",
        "independence_rationale": "SEMI 2026年第二季度300毫米晶圆厂展望的当前版本；设备支出与装机增速来自同一底层数据库，按一个证据组计。",
        "temporal_warning": None,
        "fact_count": 2,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-SEMI-DEMAND-TRANSMISSION-20251008",
        "title": "SEMI Reports Global 300mm Fab Equipment Spending Expected to Total $374 Billion Over Next Three Years",
        "title_zh": "SEMI预计2026—2028年全球300毫米晶圆厂设备支出合计3,740亿美元",
        "publisher": "SEMI",
        "published_date": "2025-10-08",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_web",
        "url": "https://www.semi.org/en/semi-press-release/semi-reports-global-300mm-fab-equipment-spending-expected-to-total-374-billion-dollars-over-next-three-years",
        "local_locator": None,
        "local_location_detail": "Segment Growth与Regional Growth",
        "excerpt": (
            "Logic & Micro is projected at $175 billion of equipment investment from 2026 to 2028, led by foundries and sub-2nm build-outs for AI workloads. "
            "Memory is projected at $136 billion, with AI training driving HBM and inference driving storage and 3D NAND. "
            "Automotive electronics, IoT and robotics support mature-node investment, while regional self-sufficiency supports local capacity."
        ),
        "excerpt_zh": "2026—2028年逻辑与微处理器设备投资预计1,750亿美元，主要由晶圆代工和面向AI负载的2纳米以下扩产驱动；存储预计1,360亿美元，训练需求推动HBM、推理产生的数据推动存储和3D NAND；汽车电子、物联网和机器人支持成熟制程投资，各地区自给政策支持本地产能。",
        "independence_key": "SEMI_300MM_EQUIPMENT_OUTLOOK_20251008",
        "independence_rationale": "SEMI 2025年10月发布的300毫米设备投资与终端驱动展望；用于解释方向，不把设备支出换算成硅片片数。",
        "temporal_warning": None,
        "fact_count": 6,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-MICRON-SINGAPORE-20260127",
        "title": "Micron Breaks Ground on Advanced Wafer Fabrication Facility in Singapore",
        "title_zh": "美光新加坡先进NAND晶圆厂开工",
        "publisher": "Micron Technology",
        "published_date": "2026-01-27",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_pdf",
        "url": "https://investors.micron.com/node/50031/pdf",
        "local_locator": None,
        "local_location_detail": "第1页第1—21行",
        "excerpt": (
            "Micron broke ground on an advanced wafer fabrication facility within its existing NAND complex in Singapore. "
            "The planned investment is approximately US$24 billion over 10 years and wafer output is scheduled to begin in the second half of 2028. "
            "Micron will manage the pace of capacity ramps to align with market demand."
        ),
        "excerpt_zh": "美光在新加坡既有NAND制造园区内为先进晶圆制造设施举行开工；计划十年投资约240亿美元，晶圆产出计划于2028年下半年开始，并将按市场需求控制爬坡节奏。",
        "independence_key": "MICRON_SINGAPORE_NAND_FAB_20260127",
        "independence_rationale": "美光当前一手项目公告，直接支持新加坡项目的主体、开工、产品、投资、投产目标与爬坡边界。",
        "temporal_warning": None,
        "fact_count": 5,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-SK-SILTRON-SR2025",
        "title": "SK Siltron Sustainability Report 2025",
        "title_zh": "SK Siltron 2025年可持续发展报告",
        "publisher": "SK Siltron",
        "published_date": "2025",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "en",
        "source_type": "official_pdf",
        "url": "https://www.sksiltron.com/en/download/2025_SKSiltron_Sustainabiliytreport.pdf",
        "local_locator": None,
        "local_location_detail": "第7页产品组合与第48页研发历程",
        "excerpt": (
            "SK siltron supplies polished and epitaxial wafers for 300mm memory and non-memory applications, including HBM, DRAM, NAND, GPU/AI, MPU, logic and CIS. "
            "Its R&D history lists a 2nm epitaxial wafer for 300mm logic in June 2024."
        ),
        "excerpt_zh": "SK Siltron供应面向300毫米存储和非存储应用的抛光片与外延片，覆盖HBM、DRAM、NAND、GPU/AI、MPU、逻辑和CIS；研发历程列出2024年6月完成面向300毫米2纳米逻辑的外延片开发。",
        "independence_key": "SK_SILTRON_SUSTAINABILITY_REPORT_2025",
        "independence_rationale": "SK Siltron发行人报告；用于证明产品能力与技术覆盖，不推断未披露的份额、客户或当前利用率。",
        "temporal_warning": None,
        "fact_count": 3,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-PSMC-CURRENT-2026",
        "title": "PSMC Manufacturing Services and P5 Update",
        "title_zh": "力积电制造服务与P5当前状态",
        "publisher": "Powerchip Semiconductor Manufacturing Corporation",
        "published_date": "2026-03-16",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "zh",
        "source_type": "official_web",
        "url": "https://www.powerchip.com/zh-tw/insights/press-releases",
        "local_locator": None,
        "local_location_detail": "2026年3月16日P5交易完成公告及制造服务页",
        "excerpt": "力积电拥有4座12英寸晶圆厂与2座8英寸晶圆厂，每月提供40万片8英寸等效代工产能；2026年3月公司公告P5厂交易完成，未来扩产方向发生变化。",
        "excerpt_zh": "力积电拥有4座12英寸晶圆厂与2座8英寸晶圆厂，每月提供40万片8英寸等效代工产能；2026年3月公司公告P5厂交易完成，未来扩产方向发生变化。",
        "independence_key": "PSMC_CURRENT_CAPACITY_AND_P5_202603",
        "independence_rationale": "力积电当前官方制造能力与P5项目状态，用于候选覆盖和反方检查；8英寸等效不能转换为12英寸新增量。",
        "temporal_warning": None,
        "fact_count": 3,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-NEXCHIP-PHASE3-20240926",
        "title": "Announcement on Capital Increase and Investor Introduction for Nexchip Phase III",
        "title_zh": "晶合集成三期项目增资扩股公告",
        "publisher": "合肥晶合集成电路股份有限公司",
        "published_date": "2024-09-26",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "zh",
        "source_type": "official_pdf",
        "url": "https://www.nexchip.com.cn/images/zh-cn/images/report/688249_20240926_FE74.pdf",
        "local_locator": None,
        "local_location_detail": "第2页第29—37行",
        "excerpt": "晶合集成三期项目投资总额为210亿元，计划建设12英寸晶圆制造生产线，产能约5万片/月，重点布局55纳米至28纳米显示驱动、55纳米CIS、90纳米电源管理、110纳米MCU及28纳米逻辑芯片。",
        "excerpt_zh": "晶合集成三期项目投资总额为210亿元，计划建设12英寸晶圆制造生产线，产能约5万片/月，重点布局55纳米至28纳米显示驱动、55纳米CIS、90纳米电源管理、110纳米MCU及28纳米逻辑芯片。",
        "independence_key": "NEXCHIP_PHASE3_CAPACITY_20240926",
        "independence_rationale": "发行人项目公告，直接支持项目主体、计划投资、尺寸、规划月产能与产品范围；发布时间较早，不能证明2026年当前施工或爬坡状态。",
        "temporal_warning": "严重时效提醒：该资料发表于2024年，只证明当时的项目计划；2026年实际施工、设备搬入和量产状态需要新公告核验。",
        "fact_count": 5,
        "local_file_sha256": None,
    },
    {
        "source_id": "DMD-SILAN-12INCH-ANALOG-20260105",
        "title": "Silan Microelectronics Starts 12-inch High-end Analog IC Line",
        "title_zh": "士兰微12英寸高端模拟芯片产线开工",
        "publisher": "杭州士兰微电子股份有限公司",
        "published_date": "2026-01-05",
        "retrieved_at": AS_OF_DATE,
        "tier": "T1",
        "language": "zh",
        "source_type": "official_web",
        "url": "https://www.silan.com.cn/index.php/news/details/286.html",
        "local_locator": None,
        "local_location_detail": "正文第252—264行",
        "excerpt": "士兰微12英寸高端模拟集成电路生产线于2026年1月4日开工，一期规划投资100亿元，计划2027年第四季度初步通线，2030年达产并形成年产24万片12英寸模拟芯片能力；两期全部完成后规划年产54万片。",
        "excerpt_zh": "士兰微12英寸高端模拟集成电路生产线于2026年1月4日开工，一期规划投资100亿元，计划2027年第四季度初步通线，2030年达产并形成年产24万片12英寸模拟芯片能力；两期全部完成后规划年产54万片。",
        "independence_key": "SILAN_12INCH_ANALOG_LINE_20260105",
        "independence_rationale": "士兰微发行人当前项目公告，直接支持开工、一期投资、通线目标、达产目标与一期年产能；二期远期规划不并入2026—2030下限。",
        "temporal_warning": None,
        "fact_count": 6,
        "local_file_sha256": None,
    },
)


DEMAND_SUPPLEMENTAL_DATA_POINTS: tuple[dict[str, Any], ...] = (
    {
        "data_point_id": "SUP-DP001",
        "subject": "全球300毫米存储晶圆厂",
        "metric": "装机月产能",
        "period": "2026E—2027E",
        "as_of": AS_OF_DATE,
        "unit": "万片/月",
        "observations": [
            {"period": "2026E", "value": 410},
            {"period": "2027E", "value": 420},
        ],
        "source_id": "DMD-SEMI-MEMORY-20260629",
        "source_locator": "https://www.semi.org/en/taxonomy/term/46781",
        "source_excerpt": DEMAND_SUPPLEMENTAL_SOURCES[0]["excerpt"],
        "source_excerpt_zh": DEMAND_SUPPLEMENTAL_SOURCES[0]["excerpt_zh"],
        "extraction_method": "web_fetch",
        "note": "存储整体口径，不拆分DRAM、HBM和NAND。",
        "evidence_tier": "T1",
        "independence_key": "SEMI_300MM_MEMORY_2Q26",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP002",
        "subject": "全球300毫米半导体硅片",
        "metric": "年度出货面积下限",
        "period": "2028E",
        "as_of": AS_OF_DATE,
        "unit": "百万平方英寸",
        "value": 10_800,
        "source_id": "DMD-SEMI-WAFER-OUTLOOK-202509",
        "source_locator": DEMAND_SUPPLEMENTAL_SOURCES[1]["url"],
        "source_excerpt": DEMAND_SUPPLEMENTAL_SOURCES[1]["excerpt"],
        "source_excerpt_zh": DEMAND_SUPPLEMENTAL_SOURCES[1]["excerpt_zh"],
        "extraction_method": "web_fetch",
        "note": "原文为超过10,800，模型按10,800计算保守下限。",
        "evidence_tier": "T1",
        "independence_key": "SEMI_WAFER_OUTLOOK_202509",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP003",
        "subject": "全球半导体硅片供应格局",
        "metric": "供应集中度",
        "period": "当前项目页",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "全球供应主要由五家公司掌握，约90%的硅片来自东亚",
        "source_id": "DMD-NIST-GLOBALWAFERS",
        "source_locator": DEMAND_SUPPLEMENTAL_SOURCES[3]["url"],
        "source_excerpt": DEMAND_SUPPLEMENTAL_SOURCES[3]["excerpt"],
        "source_excerpt_zh": DEMAND_SUPPLEMENTAL_SOURCES[3]["excerpt_zh"],
        "extraction_method": "web_fetch",
        "note": "官方资料没有披露五家公司的精确份额。",
        "evidence_tier": "T1",
        "independence_key": "NIST_GLOBALWAFERS_FINAL_AWARD",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP004",
        "subject": "UMC Singapore Fab 12i",
        "metric": "晶圆尺寸",
        "period": "当前",
        "as_of": AS_OF_DATE,
        "unit": "英寸",
        "value": 12,
        "source_id": "DMD-UMC-FAB12I-CURRENT",
        "source_locator": DEMAND_SUPPLEMENTAL_SOURCES[4]["url"],
        "source_excerpt": DEMAND_SUPPLEMENTAL_SOURCES[4]["excerpt"],
        "source_excerpt_zh": DEMAND_SUPPLEMENTAL_SOURCES[4]["excerpt_zh"],
        "extraction_method": "web_fetch",
        "note": "与S031的3万片/月和2026量产项目公告组合使用。",
        "evidence_tier": "T1",
        "independence_key": "UMC_FAB_INFORMATION_CURRENT",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP005",
        "subject": "Nanya Fab 5A",
        "metric": "晶圆尺寸",
        "period": "历史规划",
        "as_of": AS_OF_DATE,
        "unit": "英寸",
        "value": 12,
        "source_id": "DMD-NANYA-FAB5A-12INCH",
        "source_locator": DEMAND_SUPPLEMENTAL_SOURCES[5]["url"],
        "source_excerpt": DEMAND_SUPPLEMENTAL_SOURCES[5]["excerpt"],
        "source_excerpt_zh": DEMAND_SUPPLEMENTAL_SOURCES[5]["excerpt_zh"],
        "extraction_method": "web_fetch",
        "note": "只确认2022年设计尺寸，不证明2026实际产能。",
        "evidence_tier": "T1",
        "independence_key": "NANYA_FAB5A_PLAN_2022",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP006",
        "subject": "Samsung Taylor",
        "metric": "工艺与投运目标",
        "period": "2026E",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "使用EUV生产2纳米芯片，目标2026年底前投入运营",
        "source_id": "DMD-SAMSUNG-TAYLOR-20260610",
        "source_locator": DEMAND_SUPPLEMENTAL_SOURCES[6]["url"],
        "source_excerpt": DEMAND_SUPPLEMENTAL_SOURCES[6]["excerpt"],
        "source_excerpt_zh": DEMAND_SUPPLEMENTAL_SOURCES[6]["excerpt_zh"],
        "extraction_method": "web_fetch",
        "note": "公司目标，不是已经投运的事实；月产能仍未披露。",
        "evidence_tier": "T1",
        "independence_key": "SAMSUNG_TAYLOR_UPDATE_20260610",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP007",
        "subject": "Sony熊本合志新厂",
        "metric": "下一代图像传感器合作阶段",
        "period": "2026-05",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "与台积电签署无约束力备忘录，研究利用新厂设置开发和生产线",
        "source_id": "DMD-SONY-KOSHI-20260514",
        "source_locator": DEMAND_SUPPLEMENTAL_SOURCES[7]["url"],
        "source_excerpt": DEMAND_SUPPLEMENTAL_SOURCES[7]["excerpt"],
        "source_excerpt_zh": DEMAND_SUPPLEMENTAL_SOURCES[7]["excerpt_zh"],
        "extraction_method": "web_fetch",
        "note": "尚未形成确定的产能、投资或投产承诺。",
        "evidence_tier": "T1",
        "independence_key": "SONY_TSMC_KOSHI_MOU_202605",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP008",
        "subject": "Siltronic新加坡300毫米晶圆厂",
        "metric": "客户认证与爬坡状态",
        "period": "2025",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "完成多项重要客户认证，但因需求低于原先预期而放慢扩产",
        "source_id": "DMD-SILTRONIC-AR2025",
        "source_locator": DEMAND_SUPPLEMENTAL_SOURCES[8]["url"],
        "source_excerpt": DEMAND_SUPPLEMENTAL_SOURCES[8]["excerpt"],
        "source_excerpt_zh": DEMAND_SUPPLEMENTAL_SOURCES[8]["excerpt_zh"],
        "extraction_method": "web_fetch",
        "note": "公司当前披露，证明客户认证取得进展，也证明新产能释放慢于原计划。",
        "evidence_tier": "T1",
        "independence_key": "SILTRONIC_ANNUAL_REPORT_2025",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP009",
        "subject": "Siltronic半导体硅片需求",
        "metric": "分产品周期判断",
        "period": "2025",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "存储和逻辑出现复苏迹象，功率半导体与200毫米需求仍疲弱",
        "source_id": "DMD-SILTRONIC-AR2025",
        "source_locator": DEMAND_SUPPLEMENTAL_SOURCES[8]["url"],
        "source_excerpt": (
            "Memory and Logic showed first signs of demand recovery as inventories normalized, "
            "while Power and the 200 mm market remained weak due to persistently high inventories."
        ),
        "source_excerpt_zh": "随着库存正常化，存储和逻辑出现初步需求复苏迹象；功率半导体和200毫米市场因库存持续偏高而仍然疲弱。",
        "extraction_method": "web_fetch",
        "note": "不同产品周期明显分化，不能把300毫米先进需求外推到200毫米和功率产品。",
        "evidence_tier": "T1",
        "independence_key": "SILTRONIC_ANNUAL_REPORT_2025",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP010",
        "subject": "全球300毫米晶圆厂",
        "metric": "当前装机增长方向",
        "period": "2026E—2029E",
        "as_of": AS_OF_DATE,
        "unit": "百分比",
        "observations": [
            {"period": "2026E", "value": 7},
            {"period": "2027E—2029E", "value": 7},
        ],
        "source_id": "DMD-SEMI-300MM-OUTLOOK-2Q26",
        "source_locator": "https://www.semi.org/en/products-services/market-data/300mm-fab-outlook",
        "source_excerpt": "Total installed 300mm capacity is projected to increase by 7% in 2026 and continue to grow at an approximate 7% rate from 2027 to 2029.",
        "source_excerpt_zh": "300毫米装机产能预计2026年增长7%，2027—2029年继续以约7%的速度增长。",
        "extraction_method": "web_fetch",
        "note": "行业预测；2027—2029为约数，不能解释为逐年精确绝对量。",
        "evidence_tier": "T1",
        "independence_key": "SEMI_300MM_FAB_OUTLOOK_2Q26",
        "fact_type": "industry_forecast",
    },
    {
        "data_point_id": "SUP-DP011",
        "subject": "全球300毫米晶圆厂终端驱动",
        "metric": "终端到晶圆厂投资的产品结构",
        "period": "2026E—2028E",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "AI负载推动2纳米以下逻辑扩产，AI训练推动HBM，推理数据推动NAND；汽车、物联网和机器人支持成熟制程投资",
        "source_id": "DMD-SEMI-DEMAND-TRANSMISSION-20251008",
        "source_locator": "https://www.semi.org/en/semi-press-release/semi-reports-global-300mm-fab-equipment-spending-expected-to-total-374-billion-dollars-over-next-three-years",
        "source_excerpt": "AI workloads support sub-2nm build-outs; AI training boosts HBM, inference drives storage and 3D NAND, while automotive electronics, IoT and robotics support mature-node investment.",
        "source_excerpt_zh": "AI负载支持2纳米以下扩产；AI训练推动HBM，推理推动存储和3D NAND，汽车电子、物联网和机器人支持成熟制程投资。",
        "extraction_method": "web_fetch",
        "note": "设备投资只用于说明驱动和项目方向，不能直接换算硅片片数。",
        "evidence_tier": "T1",
        "independence_key": "SEMI_300MM_EQUIPMENT_OUTLOOK_20251008",
        "fact_type": "industry_forecast",
    },
    {
        "data_point_id": "SUP-DP012",
        "subject": "Micron Singapore Advanced NAND Fab",
        "metric": "开工、投资与投产目标",
        "period": "2026-01—2028H2E",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "2026年1月开工；计划十年投资约240亿美元；晶圆产出计划2028年下半年开始",
        "source_id": "DMD-MICRON-SINGAPORE-20260127",
        "source_locator": "https://investors.micron.com/node/50031/pdf",
        "source_excerpt": "Micron broke ground on an advanced wafer fabrication facility in Singapore; planned investment is approximately US$24 billion over 10 years and wafer output is scheduled to begin in the second half of 2028.",
        "source_excerpt_zh": "美光新加坡先进晶圆制造设施于2026年1月开工，计划十年投资约240亿美元，晶圆产出计划于2028年下半年开始。",
        "extraction_method": "web_fetch",
        "note": "公司目标；月产能未披露，且爬坡速度将按市场需求调整。",
        "evidence_tier": "T1",
        "independence_key": "MICRON_SINGAPORE_NAND_FAB_20260127",
        "fact_type": "company_target",
    },
    {
        "data_point_id": "SUP-DP013",
        "subject": "SK Siltron",
        "metric": "300毫米产品能力",
        "period": "2025",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "抛光片与外延片覆盖HBM、DRAM、NAND、GPU/AI、MPU、逻辑和CIS；披露2纳米逻辑外延片研发能力",
        "source_id": "DMD-SK-SILTRON-SR2025",
        "source_locator": "https://www.sksiltron.com/en/download/2025_SKSiltron_Sustainabiliytreport.pdf",
        "source_excerpt": "SK siltron supplies polished and epitaxial wafers for 300mm memory and non-memory applications and lists a 2nm epitaxial wafer for 300mm logic.",
        "source_excerpt_zh": "SK Siltron的300毫米抛光片与外延片覆盖存储和非存储应用，并披露2纳米逻辑外延片研发能力。",
        "extraction_method": "web_fetch",
        "note": "只证明产品与研发能力，不证明当前市场份额、客户或利用率。",
        "evidence_tier": "T1",
        "independence_key": "SK_SILTRON_SUSTAINABILITY_REPORT_2025",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP014",
        "subject": "力积电",
        "metric": "当前晶圆厂组合与P5状态",
        "period": "2026-03",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "4座12英寸厂与2座8英寸厂，合计40万片/月8英寸等效；P5交易完成",
        "source_id": "DMD-PSMC-CURRENT-2026",
        "source_locator": "https://www.powerchip.com/zh-tw/insights/press-releases",
        "source_excerpt": "力积电拥有4座12英寸晶圆厂与2座8英寸晶圆厂，每月提供40万片8英寸等效代工产能；2026年3月公司公告P5厂交易完成。",
        "source_excerpt_zh": "力积电拥有4座12英寸晶圆厂与2座8英寸晶圆厂，每月提供40万片8英寸等效代工产能；2026年3月公司公告P5厂交易完成。",
        "extraction_method": "web_fetch",
        "note": "8英寸等效为公司总能力，不是2026—2030新增12英寸月产能。",
        "evidence_tier": "T1",
        "independence_key": "PSMC_CURRENT_CAPACITY_AND_P5_202603",
        "fact_type": "fact",
    },
    {
        "data_point_id": "SUP-DP015",
        "subject": "晶合集成三期",
        "metric": "规划投资、月产能与产品范围",
        "period": "2024-09计划",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "投资210亿元；规划12英寸5万片/月；覆盖55—28纳米DDIC、55纳米CIS、90纳米电源管理、110纳米MCU和28纳米逻辑",
        "source_id": "DMD-NEXCHIP-PHASE3-20240926",
        "source_locator": "https://www.nexchip.com.cn/images/zh-cn/images/report/688249_20240926_FE74.pdf",
        "source_excerpt": "晶合集成三期项目投资总额为210亿元，计划建设12英寸晶圆制造生产线，产能约5万片/月。",
        "source_excerpt_zh": "晶合集成三期项目投资总额为210亿元，计划建设12英寸晶圆制造生产线，产能约5万片/月。",
        "extraction_method": "web_fetch",
        "note": "2024年公司计划；缺少2026年当前施工、设备搬入、投产和爬坡证据，不进入公开片数下限。",
        "evidence_tier": "T1",
        "independence_key": "NEXCHIP_PHASE3_CAPACITY_20240926",
        "fact_type": "company_target",
    },
    {
        "data_point_id": "SUP-DP016",
        "subject": "士兰微12英寸高端模拟产线一期",
        "metric": "开工、通线目标与一期达产能力",
        "period": "2026-01—2030E",
        "as_of": AS_OF_DATE,
        "unit": "文本",
        "value": "2026年1月4日开工；2027年第四季度初步通线；2030年达产；一期年产24万片12英寸模拟芯片",
        "source_id": "DMD-SILAN-12INCH-ANALOG-20260105",
        "source_locator": "https://www.silan.com.cn/index.php/news/details/286.html",
        "source_excerpt": "一期规划投资100亿元，计划于2027年四季度初步通线，并于2030年实现达产，届时将形成年产24万片12英寸模拟集成电路芯片的生产能力。",
        "source_excerpt_zh": "一期规划投资100亿元，计划于2027年四季度初步通线，并于2030年实现达产，届时将形成年产24万片12英寸模拟集成电路芯片的生产能力。",
        "extraction_method": "web_fetch",
        "note": "一期新线折合满产2万片/月；量产与爬坡仍是公司目标，二期远期54万片/年不并入一期。",
        "evidence_tier": "T1",
        "independence_key": "SILAN_12INCH_ANALOG_LINE_20260105",
        "fact_type": "company_target",
    },
)


def align_demand_source_records(
    source_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply project-ledger evidence corrections and append fresh official sources."""
    rows = [copy.deepcopy(dict(row)) for row in source_rows]
    by_ref = {str(row.get("source_id") or row.get("ref")): row for row in rows}
    exact_excerpts = {
        "S011": (
            "TSMC Arizona's first facility began volume production of 4nm technology in fourth quarter of 2024. The second facility is installing facility systems to produce 3-nanometer and more advanced technologies and is expected to enter high volume manufacturing in the second half of 2027. In 2025, TSMC Arizona started construction of a third facility. JASM began construction of a second fab in 2025 and plans to offer 40, 22/28, 12/16, 6/7 and 3 nanometer technologies for automotive, industrial, consumer electronics and HPC applications.",
            "台积电亚利桑那第一厂于2024年第四季度开始4纳米量产；第二厂正在安装厂务系统，计划生产3纳米及更先进技术，并预计2027年下半年进入量产；第三厂于2025年开工。JASM第二厂于2025年开工，两厂计划覆盖40、22/28、12/16、6/7和3纳米，面向汽车、工业、消费电子与高性能计算。",
        ),
        "S031": (
            "The first phase of the new facility will start volume production in 2026. Up to US$5 billion will be invested to bring the first phase to full capacity of 30,000 wafers per month.",
            "新厂第一阶段计划于2026年开始批量生产；为使第一阶段达到每月3万片的满产水平，投资额最高为50亿美元。本来源没有说明晶圆尺寸，也没有说明达到满产的年份。",
        ),
        "S035": (
            "Infineon eröffnet die Smart Power Fab in Dresden. Das Investitionsvolumen beträgt fünf Milliarden Euro.",
            "英飞凌于2026年7月2日启用德累斯顿智能功率半导体工厂，投资额为50亿欧元；本公告没有说明晶圆尺寸，也没有证明当日已经开始稳定爬坡。",
        ),
        "S038": (
            "Prototype wafers have begun to demonstrate electrical characteristics, and Rapidus continues to target mass production in 2027.",
            "试制已经开始，原型晶圆开始取得电学特性；公司继续以2027年量产为目标，不能表述为已经完成全部试制。",
        ),
        "S040": (
            "we expect to drive GB growth by investing in production equipment within the existing facility at our Yokkaichi and Kitakami factories",
            "公司预计通过在四日市和北上工厂现有设施内投资生产设备来推动GB增长。",
        ),
        "S041": (
            "The investment plan will take three phases to reach approximately 45,000 wafer capacity per month.",
            "该投资计划将分三期实施，最终达到每月约4.5万片的产能；本句未说明晶圆尺寸。",
        ),
        "S044": (
            "围绕“8英寸+12英寸”战略继续推进无锡十二英寸产线建设，华虹制造项目完成首批产能建设，第二阶段扩产至83K产能已完成所需的设备选型和商务流程。",
            "围绕“8英寸+12英寸”战略继续推进无锡十二英寸产线建设，华虹制造项目完成首批产能建设，第二阶段扩产至83K产能已完成所需的设备选型和商务流程；该句未说明83K的时间口径。",
        ),
        "S054": (
            "By the end of 2024, around 2 billion Euro will have been invested into this greenfield project.",
            "到2024年末，这一绿地项目累计投入约20亿欧元；本句不支持从2024年开始多年爬坡的说法。",
        ),
    }
    for ref, (excerpt, excerpt_zh) in exact_excerpts.items():
        if ref not in by_ref:
            raise ValueError(f"需求来源目录缺少{ref}")
        by_ref[ref]["excerpt"] = excerpt
        by_ref[ref]["excerpt_zh"] = excerpt_zh
    existing = set(by_ref)
    for source in DEMAND_SUPPLEMENTAL_SOURCES:
        if source["source_id"] in existing:
            raise ValueError(f"补充来源重复：{source['source_id']}")
        rows.append(copy.deepcopy(source))
    return rows


def synchronize_demand_project_ledger(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep the public project ledger aligned with reviewed and supplemental evidence."""
    result = copy.deepcopy(dict(payload))
    projects = list(result.get("projects") or [])
    by_id = {str(project["project_id"]): project for project in projects}

    by_id["P005"]["model_treatment"] = (
        "进入公开可量化项目情景子集；按公司目标年份逐年爬坡，不把设计产能视为已实现采购。"
    )

    taylor = by_id["P006"]
    taylor.update(
        {
            "node": "2纳米（公司2026年目标）",
            "construction_start": None,
            "production_start": "2026年底前投入运营（公司目标）",
            "status_as_of": "公司计划使用EUV生产2纳米芯片，并以2026年底前投入运营为目标；当前尚不能视为已经投产",
            "source_ids": list(dict.fromkeys([*taylor.get("source_ids", []), "DMD-SAMSUNG-TAYLOR-20260610"])),
            "model_treatment": "当前资料未披露月产能；只用于先进逻辑需求方向和时间监控。",
        }
    )

    hua_hong = by_id["P011"]
    hua_hong.update(
        {
            "node": None,
            "product": None,
            "wspm": None,
            "capacity_scope": "第二阶段扩产目标83K；中报未说明按月或按年的时间口径",
            "construction_start": None,
            "production_start": None,
            "status_as_of": "截至2025年6月底已完成首批设备搬入、装机和交付；第二阶段已完成设备选型和商务流程",
            "model_treatment": "83K缺少时间口径，不能换算月产能，也不进入新增片数求和。",
        }
    )

    umc = by_id["P012"]
    umc.update(
        {
            "wafer_diameter_mm": 300,
            "node": None,
            "product": None,
            "production_start": "2026年开始批量生产（公司计划）",
            "full_capacity_date": None,
            "status_as_of": "第一阶段计划2026年开始批量生产；每月3万片是满产规模，但公开资料没有给出满产年份",
            "source_ids": list(dict.fromkeys([*umc.get("source_ids", []), "DMD-UMC-FAB12I-CURRENT"])),
            "model_treatment": "进入公开可量化项目情景子集；2026年开始爬坡是公司计划，满产节奏采用显式研究假设，不当作已披露事实。",
        }
    )
    if isinstance(umc.get("investment"), dict):
        umc["investment"]["scope"] = "第一阶段最高"

    nanya = by_id["P021"]
    nanya.update(
        {
            "wafer_diameter_mm": 300,
            "production_start": None,
            "full_capacity_date": None,
            "status_as_of": "2022年资料计划2025年完成建设；当前实际投产和爬坡尚需新的公司证据",
            "source_ids": list(dict.fromkeys([*nanya.get("source_ids", []), "DMD-NANYA-FAB5A-12INCH"])),
            "capacity_scope": "2022年三期设计满产；当前实际爬坡公开信息不足",
            "evidence_grade": "A（历史规划）",
            "model_treatment": "历史设计规模只进入项目图谱；没有当前实际产能前不计入2026—2030新增量。",
        }
    )

    kioxia = by_id["P022"]
    kioxia["model_treatment"] = "公司优先在现有厂房内追加设备推动GB增长；月产能和新增原生硅片量未披露。"

    crolles = by_id["P030"]
    crolles.update(
        {
            "wspm": round(14_000 * 52 / 12),
            "capacity_scope": "2027年目标1.4万片/周，换算约6.07万片/月；基期未披露，不能视为净增",
            "production_start": None,
            "full_capacity_date": None,
            "status_as_of": "公司目标在2027年达到每周1.4万片；现有资料没有披露基期或达到目标的具体爬坡节点",
            "model_treatment": "只展示2027目标总量；没有基期，不能进入净增硅片需求求和。",
        }
    )

    by_id["P003"].update(
        {
            "node": None,
            "product": None,
            "production_start": None,
            "status_as_of": "第三厂已于2025年开工；项目级工艺和投产年份目前没有直接披露",
            "model_treatment": "只确认项目已开工；项目级工艺、投产年份和月产能尚未公开。",
        }
    )
    by_id["P004"].update(
        {
            "node": "40纳米、22/28纳米、12/16纳米、6/7纳米；2025年报另称二厂计划3纳米",
            "construction_start": None,
            "status_as_of": "2025年在建；Fab 1与Fab 2合计产能不能拆成Fab 2净增",
        }
    )
    by_id["P007"].update(
        {
            "node": None,
            "production_start": None,
            "status_as_of": "Fab 52已被公司列为先进逻辑大批量制造厂；当前保留摘录未披露项目级工艺和爬坡日期",
        }
    )
    by_id["P010"].update(
        {
            "production_start": None,
            "status_as_of": "2025年末较2024年末新增11.1万片/月（8英寸等效，跨来源计算）",
            "source_ids": list(dict.fromkeys([*by_id["P010"].get("source_ids", []), "S068"])),
        }
    )
    by_id["P016"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "product": None,
            "production_start": None,
            "status_as_of": "2026年1月开始建设；公司仅表示首厂将在本十年后半段投产",
        }
    )
    by_id["P001"].update(
        {
            "investment": None,
            "construction_start": None,
            "full_capacity_date": None,
            "status_as_of": "第一厂于2024年第四季度开始4纳米大批量生产",
        }
    )
    by_id["P002"].update(
        {
            "node": "3纳米及更先进",
            "product": "先进逻辑",
            "construction_start": None,
            "production_start": "2027年下半年量产（公司目标）",
            "status_as_of": "厂房建设已完成，正在安装厂务系统；量产时间仍为公司目标",
        }
    )
    by_id["P014"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "construction_start": None,
            "production_start": "2027年开始DRAM初始产出（公司目标）",
            "status_as_of": "第一厂计划于2027年开始DRAM初始产出；月产能目前没有直接披露",
        }
    )
    by_id["P017"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "product": "NAND",
            "investment": {"value": 24, "currency": "USD bn", "scope": "十年计划约"},
            "construction_start": "2026-01-27",
            "production_start": "2028年下半年开始晶圆产出（公司目标）",
            "status_as_of": "已开工；公司计划2028年下半年开始晶圆产出，并按市场需求控制爬坡",
            "source_ids": ["DMD-MICRON-SINGAPORE-20260127"],
            "evidence_grade": "A",
            "model_treatment": "月产能未披露，不进入片数求和；按项目里程碑与NAND需求方向跟踪。",
        }
    )
    by_id["P018"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "investment": {"value": 20, "currency": "KRW tn", "scope": "长期计划超过"},
            "construction_start": None,
            "production_start": None,
            "status_as_of": "2026年第一季度开始晶圆投入并逐步爬坡；公司未披露月产能",
        }
    )
    by_id["P019"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "product": None,
            "production_start": None,
            "status_as_of": "建设中，计划于2027年2月启用首个洁净室；洁净室启用不等于量产",
        }
    )
    by_id["P020"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "product": None,
            "construction_start": None,
            "production_start": None,
            "status_as_of": "正在推进主体工程，公司计划2028年运营；月产能和产品组合尚未披露",
        }
    )
    by_id["P023"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "product": None,
            "model_treatment": "只确认三期建设方向；匿名产能和DRAM转述不进入核心判断。",
        }
    )
    by_id["P024"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "product": None,
            "production_start": None,
            "status_as_of": "现有产线技术升级，相关资产计划于2026年6月30日前达到可使用状态；这不是新建产线或量产日期",
        }
    )
    by_id["P026"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "product": None,
            "production_start": "2025年预计开始初始生产（2025年公告）",
            "status_as_of": "公告预计开始初始生产，当前实际爬坡尚需更新证据",
        }
    )
    by_id["P027"].update(
        {
            "node": None,
            "product": None,
            "production_start": None,
            "status_as_of": "2023年已开工，最早2026年的原计划尚待更新证据核验",
            "evidence_grade": "A（历史计划）",
        }
    )
    by_id["P028"].update(
        {
            "wafer_diameter_mm": None,
            "node": None,
            "product": "智能功率（工厂名称所示，具体产品组合目前没有直接披露）",
            "production_start": None,
            "status_as_of": "工厂于2026年7月2日启用；公开来源没有证明当日已开始稳定爬坡",
        }
    )
    by_id["P029"].update(
        {
            "node": None,
            "product": None,
            "production_start": None,
            "full_capacity_date": None,
            "status_as_of": "公司目标到2027年净增每周2,000片，折合约8,667片/月；尚未披露具体爬坡节点",
            "model_treatment": "进入公开可量化项目情景子集；净增能力由公司披露的翻倍目标推导，年度采购仍按显式爬坡情景计算。",
        }
    )
    by_id["P030"].update(
        {
            "node": None,
            "product": None,
        }
    )
    by_id["P031"].update(
        {
            "node": "300毫米半导体制造，细分产品目前没有由保留摘录确认",
            "product": "细分产品目前没有由保留摘录确认",
            "model_treatment": "只作为既有欧洲300毫米制造基础，不能据此推断具体汽车、功率或传感产品，也不计新增。",
        }
    )

    if "P032" not in by_id:
        projects.extend(
            [
                {
                    "project_id": "P032",
                    "company": "GlobalFoundries",
                    "fab_site": "Malta现有厂扩建与新建厂",
                    "company_type": "foundry",
                    "country_region": "美国",
                    "city": "Malta, New York",
                    "wafer_diameter_mm": 300,
                    "node": None,
                    "product": None,
                    "investment": None,
                    "wspm": None,
                    "capacity_scope": "两项目全部阶段完成后合计100万片/年；无法拆分新厂净增",
                    "construction_start": None,
                    "production_start": None,
                    "full_capacity_date": "未来十年以上分期",
                    "status_as_of": "长期扩建规划",
                    "source_ids": ["S032"],
                    "evidence_grade": "A",
                    "model_treatment": "总量混合现有厂与新厂且跨十年以上，只进入方向判断。",
                },
                {
                    "project_id": "P033",
                    "company": "GlobalFoundries",
                    "fab_site": "Burlington",
                    "company_type": "foundry",
                    "country_region": "美国",
                    "city": "Burlington, Vermont",
                    "wafer_diameter_mm": 200,
                    "node": "特色工艺",
                    "product": "硅基氮化镓",
                    "investment": None,
                    "wspm": None,
                    "capacity_scope": "未披露",
                    "construction_start": None,
                    "production_start": None,
                    "full_capacity_date": None,
                    "status_as_of": "改造现有设施",
                    "source_ids": ["S032"],
                    "evidence_grade": "A",
                    "model_treatment": "只确认200毫米产品方向，没有月产能时不量化。",
                },
                {
                    "project_id": "P034",
                    "company": "Sony Semiconductor Solutions / TSMC",
                    "fab_site": "Koshi新厂",
                    "company_type": "idm",
                    "country_region": "日本",
                    "city": "Koshi, Kumamoto",
                    "wafer_diameter_mm": None,
                    "node": None,
                    "product": "下一代图像传感器",
                    "investment": None,
                    "wspm": None,
                    "capacity_scope": None,
                    "construction_start": None,
                    "production_start": None,
                    "full_capacity_date": None,
                    "status_as_of": "新厂已建；双方按无约束力备忘录研究开发和生产线",
                    "source_ids": ["DMD-SONY-KOSHI-20260514"],
                    "evidence_grade": "A（状态）/C（产能）",
                    "model_treatment": "合作尚未形成确定产能、投资和投产承诺，只进入方向监控。",
                },
            ]
        )

    existing_project_ids = {str(project["project_id"]) for project in projects}
    if "P035" not in existing_project_ids:
        projects.extend(
            [
                {
                    "project_id": "P035",
                    "company": "合肥晶合集成电路股份有限公司",
                    "fab_site": "晶合集成三期",
                    "company_type": "foundry",
                    "country_region": "中国大陆",
                    "city": "合肥",
                    "wafer_diameter_mm": 300,
                    "node": "110纳米至28纳米（按产品分工艺）",
                    "product": "显示驱动、CIS、电源管理、MCU与逻辑",
                    "investment": {"value": 210, "currency": "RMB 100m", "scope": "项目计划"},
                    "wspm": 50_000,
                    "capacity_scope": "三期规划满产约5万片/月；2026年当前施工和爬坡尚待更新",
                    "construction_start": None,
                    "production_start": None,
                    "full_capacity_date": None,
                    "status_as_of": "2024年公司公告的三期项目计划；本轮未取得足以确认2026年施工、设备搬入或量产的更新证据",
                    "source_ids": ["DMD-NEXCHIP-PHASE3-20240926"],
                    "evidence_grade": "A（历史计划）",
                    "model_treatment": "规划月产能与投资可展示，但时点证据陈旧，未取得当前施工和爬坡前不进入2026—2030公开可量化项目子集。",
                },
                {
                    "project_id": "P036",
                    "company": "杭州士兰微电子股份有限公司",
                    "fab_site": "厦门12英寸高端模拟集成电路产线一期",
                    "company_type": "idm",
                    "country_region": "中国大陆",
                    "city": "厦门",
                    "wafer_diameter_mm": 300,
                    "node": None,
                    "product": "高端模拟集成电路",
                    "investment": {"value": 100, "currency": "RMB 100m", "scope": "一期规划"},
                    "wspm": 20_000,
                    "capacity_scope": "一期2030年达产24万片/年，折合2万片/月；二期远期规划不计入",
                    "construction_start": "2026-01-04",
                    "production_start": "2027年第四季度初步通线并投产（公司目标）",
                    "full_capacity_date": "2030年（公司目标）",
                    "status_as_of": "2026年1月已开工；通线、投产与达产时点仍为公司目标",
                    "source_ids": ["DMD-SILAN-12INCH-ANALOG-20260105"],
                    "evidence_grade": "A",
                    "model_treatment": "一期满产能力和时点可复算并进入公开可量化项目子集；年度爬坡使用显式研究假设，输出不能写成已实现采购或采购的最低值。",
                },
            ]
        )

    fact_fields = (
        "wafer_diameter_mm",
        "node",
        "product",
        "investment",
        "wspm",
        "capacity_scope",
        "construction_start",
        "production_start",
        "full_capacity_date",
        "status_as_of",
    )
    project_ids = [str(project["project_id"]) for project in projects]
    if len(project_ids) != len(set(project_ids)):
        raise ValueError("需求侧项目台账存在重复project_id")
    for project in projects:
        refs = list(dict.fromkeys(str(ref) for ref in project.get("source_ids") or [] if str(ref)))
        if not refs:
            raise ValueError(f"{project['project_id']} 缺少项目来源")
        project["field_evidence"] = {
            field: refs
            for field in fact_fields
            if project.get(field) not in (None, "")
        }
        missing_fields = [field for field in fact_fields if project.get(field) in (None, "")]
        project["evidence_gap_note"] = (
            "以下字段在本轮保留摘录中没有直接证据，保持为空，不从其他项目或行业均值继承："
            + "、".join(missing_fields)
            if missing_fields
            else "本行展示字段均已绑定到项目来源；仍不得把项目目标当作实际产出。"
        )
        unsupported = [
            field
            for field in fact_fields
            if project.get(field) not in (None, "") and field not in project["field_evidence"]
        ]
        if unsupported:
            raise ValueError(f"{project['project_id']} 存在未绑定证据的非空字段：{unsupported}")

    result["projects"] = projects
    metadata = copy.deepcopy(dict(result.get("metadata") or {}))
    metadata["project_count"] = len(projects)
    metadata["null_means"] = "公开资料或本轮保留摘录未直接披露；不是零。"
    metadata["field_evidence_contract"] = "每个展示的非空事实字段都必须列出source_ids；缺证字段保持为空。"
    result["metadata"] = metadata
    result["scope"] = f"截至{AS_OF_DATE}共核验{len(projects)}项全球晶圆厂项目，包含可量化项目、定性项目和明确限制；不是全球项目全集。"
    result["synchronization_note"] = (
        "项目尺寸、产能、时间和状态已与逐点证据审计及2026年补充一手来源对账；"
        "华虹83K不再换算为月产能，Crolles周产能已正确换算，Taylor与UMC/Nanya的尺寸或时间由新增官方来源补强；"
        "Micron新加坡项目已改用2026年公司公告，所有非空事实字段均附字段级来源映射。"
    )
    if metadata["project_count"] != len(result["projects"]):
        raise AssertionError("项目台账元数据计数与数组长度不一致")
    return result


DEMAND_SUPPLIER_RANKING_ROWS: tuple[dict[str, Any], ...] = (
    {
        "rank": 1,
        "supplier": "上海超硅",
        "position": "当前瓶颈能力与利用率口径最完整",
        "evidence": "2025年12英寸瓶颈年产能367万片，折合约30.58万片/月，利用率75.18%",
        "why": "可核验的当前瓶颈能力和利用率比单纯规划产能更适合判断需求兑现；若订单增加，利用率提升具有直接弹性。",
        "watch": "瓶颈工序扩充、利用率、客户认证和外延片项目落地",
        "source_refs": ["S058"],
    },
    {
        "rank": 2,
        "supplier": "西安奕材",
        "position": "12英寸规划规模大，实际兑现仍待核验",
        "evidence": "公司规划到2026年形成120万片/月12英寸硅片产能；当前稳定可售产能与利用率尚未直接披露",
        "why": "规划规模与客户验证显示潜力，但不能把规划产能当作当前稳定供给；持续亏损要求用实际销量、价格、良率、利用率和现金流验证。",
        "watch": "当前稳定可售产能、季度销量、单价、利用率、毛利和经营现金流",
        "source_refs": ["S059"],
    },
    {
        "rank": 3,
        "supplier": "沪硅产业",
        "position": "产品与客户基础较完整，当前订单需重新核验",
        "evidence": "历史监管资料确认30万片/月300毫米项目及多家客户认证",
        "why": "先进规格和客户基础较强，但核心客户证据来自2021年，只能证明历史能力，不能直接当作2026年订单。",
        "watch": "当前客户复购、分产品销量与新增扩产利用率",
        "source_refs": ["S057"],
    },
    {
        "rank": 4,
        "supplier": "立昂微",
        "position": "12英寸销量增长快，在建项目存在延期",
        "evidence": "2025年12英寸销量178.57万片、名义产能30万片/月，硅片业务收入增长65.63%",
        "why": "销量和收入正在增长，但多项12英寸衬底及外延项目仍建设或延期，需检验新增折旧能否被订单吸收。",
        "watch": "在建项目进度、12英寸销量、单位价格和毛利",
        "source_refs": ["S061"],
    },
    {
        "rank": 5,
        "supplier": "上海合晶",
        "position": "外延片差异化明确，规模较小",
        "evidence": "现有12英寸功率硅片4万片/月，郑州二期CIS目标6万片/月，远期逻辑规划10万片/月",
        "why": "产品定位与功率、CIS需求匹配，但近端规模和投产时点低于综合型供应商，受益更偏细分。",
        "watch": "郑州二期投产、CIS客户认证和外延片价格",
        "source_refs": ["S062"],
    },
    {
        "rank": 6,
        "supplier": "TCL中环半导体材料",
        "position": "销量增长但库存同步上升，尺寸结构不足",
        "evidence": "2025年半导体材料销量增长23.99%，期末库存增长35.87%",
        "why": "总销量增长不能证明12英寸高规格受益，库存增速更快要求先验证产品结构、去库和价格。",
        "watch": "12英寸占比、库存天数、平均售价和客户认证",
        "source_refs": ["S060"],
    },
)


DEMAND_CANDIDATE_COVERAGE_ROWS: tuple[dict[str, Any], ...] = (
    {
        "candidate": "力积电",
        "conclusion": "本轮没有找到可核验的2026—2030新增月产能公告，因此不进入定量排名。",
        "next": "补充最新年报、法说会或政府项目文件后再判断。",
        "source_refs": [],
    },
    {
        "candidate": "Sony",
        "conclusion": "已补入熊本合志新厂与台积电的下一代图像传感器合作研究；目前仍是无约束力备忘录阶段。",
        "next": "等待合资协议、晶圆尺寸、月产能、投资与投产时间。",
        "source_refs": ["DMD-SONY-KOSHI-20260514"],
    },
    {
        "candidate": "GlobalFoundries",
        "conclusion": "已补入Malta长期扩建和Burlington 200毫米改造；Malta的100万片/年混合多个项目且跨十年以上。",
        "next": "补充2026—2030分阶段净增月产能，才能进入片数模型。",
        "source_refs": ["S032"],
    },
)
