from __future__ import annotations

from typing import Any


def _source(
    ref: str,
    title: str,
    publisher: str,
    *,
    channel: str,
    tier: str,
    independence_key: str,
    excerpt: str,
    url: str | None = None,
    local_path: str | None = None,
    date: str | None = None,
    language: str = "zh",
    title_zh: str | None = None,
    excerpt_zh: str | None = None,
    review_status: str = "pass",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ref": ref,
        "title": title,
        "publisher": publisher,
        "source_tier": tier,
        "source_review_status": review_status,
        "excerpt": excerpt,
        "language": language,
        "independence_key": independence_key,
        "independence_rationale": (
            f"该记录归入“{independence_key}”；同一发布主体、同一底层报告或同一公告的转载不重复增加独立性。"
        ),
        "source_channel": channel,
    }
    if url:
        row["url"] = url
    if local_path:
        row["local_path"] = local_path
    if date:
        row["published_at"] = date
    if language.startswith("en"):
        row["title_zh"] = title_zh or title
        row["excerpt_zh"] = excerpt_zh or excerpt
    return row


SOURCES: list[dict[str, Any]] = [
    _source(
        "r-huayou-ar2025",
        "2025 Annual Report",
        "浙江华友钴业股份有限公司",
        channel="report",
        tier="S",
        independence_key="huayou_2025_annual_report",
        local_path="papers/华友钴业/公司财报/华友钴业_2025年年度报告.pdf",
        date="2026-04-08",
        language="en",
        title_zh="华友钴业2025年年度报告",
        excerpt=(
            "In 2025 the company recorded revenue of RMB 81.019 billion and net profit attributable "
            "to shareholders of RMB 6.110 billion; nickel product shipments were about 292,500 metal tonnes."
        ),
        excerpt_zh="2025年公司实现营业收入810.19亿元、归母净利润61.10亿元，镍产品出货约29.25万金属吨。",
    ),
    _source(
        "r-huayou-ar2024",
        "华友钴业2024年年度报告",
        "浙江华友钴业股份有限公司",
        channel="report",
        tier="S",
        independence_key="huayou_2024_annual_report",
        local_path="papers/华友钴业/公司财报/华友钴业_2024年年度报告.pdf",
        date="2025-04-19",
        excerpt="2024年公司实现营业收入609.46亿元、归母净利润41.55亿元；镍产品出货18.43万金属吨，Arcadia锂精矿出货约40万吨。",
    ),
    _source(
        "r-huayou-ar2023",
        "华友钴业2023年年度报告",
        "浙江华友钴业股份有限公司",
        channel="report",
        tier="S",
        independence_key="huayou_2023_annual_report",
        local_path="papers/华友钴业/公司财报/华友钴业_2023年年度报告.pdf",
        date="2024-04-20",
        excerpt="2023年公司实现营业收入663.04亿元、归母净利润33.51亿元，处于印尼镍项目集中建设与爬坡阶段。",
    ),
    _source(
        "r-huayou-h12025",
        "华友钴业2025年半年度报告",
        "浙江华友钴业股份有限公司",
        channel="report",
        tier="S",
        independence_key="huayou_2025_interim_report",
        local_path="papers/华友钴业/公司财报/华友钴业_2025年半年度报告.pdf",
        date="2025-08-18",
        excerpt="2025年上半年报告披露Pomalaa工业园和12万吨HPAL项目在建工程、投资预算与工程进度，并披露主要在建材料项目。",
    ),
    _source(
        "r-huayou-q12026",
        "华友钴业2026年第一季度报告",
        "浙江华友钴业股份有限公司",
        channel="report",
        tier="S",
        independence_key="huayou_2026_q1_report",
        local_path="papers/华友钴业/公司财报/华友钴业_2026年第一季度报告.pdf",
        date="2026-04-17",
        excerpt="2026年第一季度公司实现营业收入258.04亿元、归母净利润24.97亿元、经营现金流11.75亿元，购建长期资产现金支出47.37亿元。",
    ),
    _source(
        "r-huachuang-20260515",
        "华友钴业深度研究：前瞻布局锂电上游资源，尽享锂钴镍景气周期",
        "华创证券",
        channel="report",
        tier="B",
        independence_key="huachuang_huayou_model_20260515",
        local_path="papers/华友钴业/2026-05-15_华创证券_华友钴业_华友钴业（603799）：深度研究报告：前瞻布局锂电上游资源，尽享锂钴镍景气周期.pdf",
        date="2026-05-15",
        excerpt="报告按钴、铜、镍、锂、前驱体和正极材料拆分2026—2028年销量、价格、成本与利润，并给出归母净利润预测。",
    ),
    _source(
        "r-boc-20260430",
        "华友钴业：26Q1业绩同比高增，一体化优势持续释放",
        "中银国际证券",
        channel="report",
        tier="B",
        independence_key="boc_huayou_model_20260430",
        local_path="papers/华友钴业/2026-04-30_中银国际_华友钴业_华友钴业（603799）：26q1业绩同比高增，一体化优势持续释放.pdf",
        date="2026-04-30",
        excerpt="报告基于2026年一季度业绩、资源价格和项目进度预测2026—2028年收入与归母净利润。",
    ),
    _source(
        "r-csc-20260525",
        "华友钴业：镍钴锂价格进入上升通道，一体化优势显著",
        "中信建投证券",
        channel="report",
        tier="B",
        independence_key="csc_huayou_model_20260525",
        local_path="papers/华友钴业/2026-05-25_中信建投_华友钴业_华友钴业（603799）：镍钴锂价格进入上升通道，一体化优势显著.pdf",
        date="2026-05-25",
        excerpt="报告围绕镍钴锂价格、印尼HPAL、Arcadia与下游材料业务预测2026—2028年归母净利润。",
    ),
    _source(
        "r-citi-20260721",
        "华友钴业：模型更新；目标价调整至63.8元/股",
        "花旗",
        channel="report",
        tier="B",
        independence_key="citi_huayou_model_20260721",
        local_path="papers/华友钴业/2026-07-21_citi_华友钴业_华友钴业（603799）：模型更新；目标价调整至63.8元_股，维持买入评级.pdf",
        date="2026-07-21",
        excerpt="花旗更新了硫磺与MHP成本、材料利润率和2026—2028年盈利预测，形成偏谨慎的外部压力情景。",
    ),
    _source(
        "r-nickel-20260525",
        "镍行业专题：供需逐步趋紧的关键金属",
        "国信证券",
        channel="report",
        tier="B",
        independence_key="guosen_nickel_outlook_20260525",
        local_path="papers/华友钴业/20260525-国信证券-镍行业专题：金供需逐步趋紧的关键金属.pdf",
        date="2026-05-25",
        excerpt="报告拆分印尼矿石、RKEF、HPAL、不锈钢与电池需求，并给出政策松紧下的镍供需情景。",
    ),
    _source(
        "r-nickel-20260718",
        "镍周报：印尼镍矿政策预期修正，镍价短期企稳反弹",
        "五矿期货",
        channel="report",
        tier="B",
        independence_key="minmetals_nickel_weekly_20260718",
        local_path="papers/华友钴业/20260718-五矿期货-镍周报：印尼镍矿政策预期修正，镍价短期企稳反弹.pdf",
        date="2026-07-18",
        excerpt="周报跟踪印尼RKAB政策预期、镍矿补充、库存和镍价变化，显示配额预期仍在动态修正。",
    ),
    _source(
        "r-cobalt-20260211",
        "2026年钴行业策略：地缘格局引机遇，供减需增价格望新高",
        "东方证券",
        channel="report",
        tier="B",
        independence_key="orient_cobalt_strategy_20260211",
        local_path="papers/华友钴业/20260211-东方证券-2026年钴行业策略：地缘格局引机遇，供减需增价格望新高.pdf",
        date="2026-02-11",
        excerpt="报告讨论DRC出口配额、库存、印尼伴生钴和下游需求，对2026—2027年有效供需做情景估算。",
    ),
    _source(
        "r-cobalt-20260616",
        "2026年半年度策略报告（钴）：供需偏紧格局缓解，钴价承压回落",
        "中信期货",
        channel="report",
        tier="B",
        independence_key="citicfutures_cobalt_20260616",
        local_path="papers/华友钴业/20260616-中信期货-有色与新材料2026年半年度策略报告（钴）：供需偏紧格局缓解，钴价承压回落.pdf",
        date="2026-06-16",
        excerpt="报告区分理论产量、有效供应、配额、库存与需求，给出2026—2027年偏紧但可能缓解的供需路径。",
    ),
    _source(
        "r-lithium-20260614",
        "碳酸锂行业深度报告：供需紧平衡趋势强化，价格中枢有望抬升",
        "浙商证券",
        channel="report",
        tier="B",
        independence_key="zheshang_lithium_20260614",
        local_path="papers/华友钴业/20260614-浙商证券-碳酸锂行业深度报告：供需紧平衡趋势强化，价格中枢有望抬升.pdf",
        date="2026-06-14",
        excerpt="报告按矿山、盐湖、云母、回收和需求场景给出2026—2028年全球碳酸锂当量供需路径。",
    ),
    _source(
        "r-lithium-20260618",
        "全球锂资源供应全面盘点",
        "华鑫证券",
        channel="report",
        tier="B",
        independence_key="chinfortune_lithium_supply_20260618",
        local_path="papers/华友钴业/20260618-华鑫证券-能源金属行业深度报告：全球锂资源供应全面盘点.pdf",
        date="2026-06-18",
        excerpt="报告逐项目盘点澳大利亚、南美、非洲、中国和北美锂资源产能、成本、投产与延期风险。",
    ),
    _source(
        "w-iea-critical-2026",
        "Global Critical Minerals Outlook 2026",
        "International Energy Agency",
        channel="web",
        tier="S",
        independence_key="iea_global_critical_minerals_2026",
        url="https://www.iea.org/reports/global-critical-minerals-outlook-2026",
        date="2026-07-16",
        language="en",
        title_zh="IEA《全球关键矿产展望2026》",
        excerpt="Demand for critical minerals almost doubles to 2040 in STEPS; lithium rises more than threefold and nickel grows by 50% to 90%.",
        excerpt_zh="在既定政策情景下，关键矿产需求到2040年接近翻倍；锂需求超过三倍，镍需求增长约50%—90%。",
    ),
    _source(
        "w-iea-market-2026",
        "Market overview – Global Critical Minerals Outlook 2026",
        "International Energy Agency",
        channel="web",
        tier="S",
        independence_key="iea_global_critical_minerals_2026",
        url="https://www.iea.org/reports/global-critical-minerals-outlook-2026/market-overview",
        date="2026-07-16",
        language="en",
        title_zh="IEA《全球关键矿产展望2026》市场概览",
        excerpt="Lithium demand grew around 25% per year on average over the past two years while battery-mineral investment fell sharply in 2025.",
        excerpt_zh="过去两年锂需求年均增长约25%，但2025年电池矿产投资与勘探支出明显下降。",
    ),
    _source(
        "w-iea-outlook-2026",
        "Outlook – Global Critical Minerals Outlook 2026",
        "International Energy Agency",
        channel="web",
        tier="S",
        independence_key="iea_global_critical_minerals_2026",
        url="https://www.iea.org/reports/global-critical-minerals-outlook-2026/outlook",
        date="2026-07-16",
        language="en",
        title_zh="IEA《全球关键矿产展望2026》供需展望",
        excerpt="The base case shows a cobalt supply gap above 25% in 2035 under the DRC quota, while nickel has only a slight gap and early-stage projects may fill it.",
        excerpt_zh="在DRC配额持续的基准情景下，2035年钴供应缺口超过25%；镍仅有轻微缺口，早期项目若落地可能填补。",
    ),
    _source(
        "w-iea-ev-2026",
        "Global EV Outlook 2026 – Electric vehicle batteries",
        "International Energy Agency",
        channel="web",
        tier="S",
        independence_key="iea_global_ev_outlook_2026",
        url="https://www.iea.org/reports/global-ev-outlook-2026/electric-vehicle-batteries",
        date="2026-05-01",
        language="en",
        title_zh="IEA《全球电动汽车展望2026》电池章节",
        excerpt="LFP accounted for more than 55% of global EV batteries in 2025 and more than 90% of storage batteries.",
        excerpt_zh="2025年LFP占全球电动车电池超过55%，占储能电池超过90%，限制了单位钴、镍需求强度。",
    ),
    _source(
        "w-usgs-mcs2026",
        "Mineral Commodity Summaries 2026",
        "U.S. Geological Survey",
        channel="web",
        tier="S",
        independence_key="usgs_mcs_2026",
        url="https://pubs.usgs.gov/periodicals/mcs2026/mcs2026.pdf",
        date="2026-02-05",
        language="en",
        title_zh="USGS《矿产品概要2026》",
        excerpt="The report provides 2025 world mine production, reserves, prices and market conditions for cobalt, lithium and nickel.",
        excerpt_zh="报告给出钴、锂、镍的2025年全球矿山产量、储量、价格与市场状况。",
    ),
    _source(
        "w-drc-quota",
        "DRC ARECOMS Decision No. 004/2025 – Cobalt Quota System",
        "International Energy Agency",
        channel="web",
        tier="S",
        independence_key="drc_arecoms_quota_decision_004_2025",
        url="https://www.iea.org/policies/29138-drc-arecoms-decision-no-0042025-cobalt-quota-system",
        date="2026-05-28",
        language="en",
        title_zh="DRC ARECOMS第004/2025号决定：钴出口配额制度",
        excerpt="The 2026 export quota is 96,600 tonnes, including an 87,000-tonne base quota and a 9,600-tonne strategic quota.",
        excerpt_zh="2026年出口配额为9.66万吨，其中基础配额8.70万吨、战略配额0.96万吨。",
    ),
    _source(
        "w-indonesia-esdm",
        "Kementerian ESDM Belum Putuskan Besaran RKAB Nikel 2026",
        "印尼能源与矿产资源部",
        channel="web",
        tier="S",
        independence_key="indonesia_esdm_rkab_2026",
        url="https://www.esdm.go.id/en?Itemid=100",
        date="2026-06-25",
        language="id",
        excerpt="印尼能源与矿产资源部在2026年6月表示，2026年全国镍RKAB总量尚未最终决定。",
    ),
    _source(
        "w-indonesia-antara",
        "Indonesia limits nickel quota expansion to support global prices",
        "ANTARA",
        channel="web",
        tier="A",
        independence_key="indonesia_nickel_quota_official_statement_202607",
        url="https://en.antaranews.com/news/422261/indonesia-limits-nickel-quota-expansion-to-support-global-prices",
        date="2026-07-10",
        language="en",
        title_zh="印尼限制镍配额扩张以支撑全球价格",
        excerpt="The ministry stated that the national nickel production quota for 2026 was capped around 250 million to 260 million tonnes.",
        excerpt_zh="印尼主管部门表示，2026年全国镍生产配额控制在约2.5亿—2.6亿吨，但仍存在企业申请调整窗口。",
    ),
    _source(
        "w-huayou-ar2025",
        "2025 Annual Report",
        "Zhejiang Huayou Cobalt Co., Ltd.",
        channel="web",
        tier="S",
        independence_key="huayou_2025_annual_report",
        url="https://www.huayou.com/Public/Uploads/uploadfile2/files/20260407/2025AnnualReportofHuayouCobalt.pdf",
        date="2026-04-08",
        language="en",
        title_zh="华友钴业2025年年度报告（官网）",
        excerpt="The annual report describes integrated nickel, cobalt and lithium resources, refining, precursors, cathode materials and recycling.",
        excerpt_zh="年报披露镍钴锂资源、冶炼、前驱体、正极材料与回收一体化业务及主要项目。",
    ),
    _source(
        "w-huayou-lithium",
        "Huayou’s First Batch of Lithium Sulfate from Zimbabwe Shipped Back to China",
        "Zhejiang Huayou Cobalt Co., Ltd.",
        channel="web",
        tier="S",
        independence_key="huayou_zimbabwe_lithium_sulfate_202604",
        url="https://www.huayou.com/en/news/corporate-news/443.html",
        date="2026-04-27",
        language="en",
        title_zh="华友钴业津巴布韦首批硫酸锂发运回国",
        excerpt="The first batch was shipped on 25 April 2026, marking the transition from construction and commissioning to stable production.",
        excerpt_zh="首批硫酸锂于2026年4月25日发运，项目从建设调试转入稳定生产阶段。",
    ),
    _source(
        "w-huayou-arcadia",
        "Huayou Cobalt's Arcadia Lithium Mine in Zimbabwe Begins Trial Production",
        "Zhejiang Huayou Cobalt Co., Ltd.",
        channel="web",
        tier="S",
        independence_key="huayou_arcadia_trial_202303",
        url="https://www.huayou.com/en/news/corporate-news/19",
        date="2023-03-26",
        language="en",
        title_zh="华友钴业Arcadia锂矿投料试产",
        excerpt="All production lines completed installation and commissioning for a 4.5-million-tonne-per-year ore processing project.",
        excerpt_zh="Arcadia年处理450万吨矿石项目完成安装调试并投料试产。",
    ),
    _source(
        "w-vale-pomalaa",
        "Indonesia Growth Project Pomalaa",
        "Vale",
        channel="web",
        tier="S",
        independence_key="vale_pomalaa_project",
        url="https://www.vale.com/zh/indonesia-growth-projects-pomalaa",
        date="2026-06-30",
        language="en",
        title_zh="Vale印尼Pomalaa增长项目",
        excerpt="The HPAL project is a joint venture of Vale, Huayou and Ford with annual capacity of 120,000 tonnes of nickel and about 15,000 tonnes of cobalt in MHP.",
        excerpt_zh="Pomalaa HPAL由Vale、华友和Ford合作，规划年产12万吨镍和约1.5万吨伴生钴。",
    ),
    _source(
        "w-vale-pomalaa-progress",
        "PT Vale’s Growth Project in IGP Pomalaa Reaches 62% Completion",
        "Vale",
        channel="web",
        tier="S",
        independence_key="vale_pomalaa_progress_2026",
        url="https://saladeimprensa.vale.com/in/w/pt-vale-s-growth-project-in-igp-pomalaa-reaches-62-completion",
        date="2026-03-01",
        language="en",
        title_zh="Vale称Pomalaa矿山增长项目完成度达到62%",
        excerpt="Vale reported 62% progress for the mining growth project while HPAL and feed preparation construction remained in progress.",
        excerpt_zh="Vale披露矿山增长项目完成度约62%，HPAL与原料准备设施仍在建设中。",
    ),
    _source(
        "w-sec-ewoyaa",
        "Elevra Announces Agreement to Sell Ewoyaa Project Interest",
        "U.S. Securities and Exchange Commission / Elevra Lithium",
        channel="web",
        tier="S",
        independence_key="elevra_ewoyaa_sale_202605",
        url="https://www.sec.gov/Archives/edgar/data/1739016/000114036126020579/ef20073008_6k.htm",
        date="2026-05-11",
        language="en",
        title_zh="Elevra披露向华友出售Ewoyaa项目权益",
        excerpt="Huayou agreed to pay US$210 million for Atlantic Lithium and about US$71 million for Elevra's Ewoyaa interests; both transactions require approvals and closing.",
        excerpt_zh="华友拟以2.10亿美元收购Atlantic Lithium，并以约0.71亿美元收购Elevra的Ewoyaa权益；交易仍需审批和交割。",
    ),
    _source(
        "w-huayou-precursor",
        "Huayou Cobalt Begins Scale Production at Indonesia Ternary Precursor Project",
        "Zhejiang Huayou Cobalt Co., Ltd.",
        channel="web",
        tier="S",
        independence_key="huayou_indonesia_precursor_202505",
        url="https://www.huayou.com/en/news/corporate-news/316.html",
        date="2025-05-07",
        language="en",
        title_zh="华友印尼三元前驱体项目进入规模化生产",
        excerpt="The second phase produced qualified products in March 2025, moving the 50,000-tonne Indonesia precursor project into scale production.",
        excerpt_zh="印尼5万吨三元前驱体项目二期于2025年3月产出合格产品，项目进入规模化生产阶段。",
    ),
    _source(
        "r-model-supply-demand",
        "Run14镍钴锂供需情景模型",
        "本研究",
        channel="report",
        tier="B",
        independence_key="run14_supply_demand_model",
        local_path="opportunity_lens/research_outputs/20260724_huayou_nickel_cobalt_lithium_run14/supply_demand_output.json",
        date="2026-07-24",
        excerpt="模型统一区分矿山产量、有效供应、出口配额和需求，并给出2026—2030年基准、紧张与宽松路径；所有情景输入均为研究假设。",
    ),
    _source(
        "r-model-financial",
        "Run14华友钴业独立财务与估值模型",
        "本研究",
        channel="report",
        tier="B",
        independence_key="run14_independent_financial_model",
        local_path="opportunity_lens/research_outputs/20260724_huayou_nickel_cobalt_lithium_run14/independent_model_output.json",
        date="2026-07-24",
        excerpt="模型从2025年分产品收入、毛利率和项目权益口径出发，估算2026—2028年收入、归母净利润、经营现金流、资本开支、自由现金流与多方法估值。",
    ),
]


def _fact(
    source_ref: str,
    entity_key: str,
    metric: str,
    value: float | str,
    unit: str,
    period: str,
    scope_key: str,
    note: str,
    *,
    extraction_method: str = "web_fetch",
    observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "source_ref": source_ref,
        "entity_key": entity_key,
        "metric": metric,
        "value": value,
        "unit": unit,
        "period": period,
        "scope_key": scope_key,
        "note": note,
        "extraction_method": extraction_method,
        "observations": observations,
    }


def build_fact_specs() -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    annual = {
        "营业收入": [353.17, 630.34, 663.04, 609.46, 810.19],
        "归母净利润": [38.98, 39.10, 33.51, 41.55, 61.10],
        "经营现金流": [-0.62, 29.14, 34.86, 124.31, 40.12],
        "资本开支": [68.47, 162.15, 168.49, 67.22, 107.58],
        "总资产": [579.89, 1105.92, 1255.20, 1365.91, 1594.38],
        "总权益": [239.01, 326.82, 447.33, 486.61, 608.21],
        "总负债": [340.88, 779.10, 807.87, 879.31, 986.17],
        "ROE": [26.60, 17.27, 11.14, 11.67, 14.34],
        "ROA": [12.38, 8.61, 5.42, 5.88, 6.93],
        "毛利率": [20.35, 18.59, 14.11, 17.23, 17.47],
        "净利率": [11.39, 9.05, 6.79, 8.46, 9.28],
    }
    for metric, values in annual.items():
        unit = "%" if metric in {"ROE", "ROA", "毛利率", "净利率"} else "亿元人民币"
        facts.append(
            _fact(
                "r-huayou-ar2025",
                "huayou_integrated",
                f"华友钴业年度{metric}",
                f"2021—2025年{metric}序列",
                unit,
                "2021—2025",
                f"huayou_annual_{metric}",
                f"同一公司、同一口径的五年{metric}合并为一个序列，不按年份拆成多个证据点。",
                extraction_method="pdf_direct",
                observations=[
                    {"period": str(year), "value_num": value}
                    for year, value in zip(range(2021, 2026), values)
                ],
            )
        )

    segments = [
        ("钴产品", 50.30, 36.78, 4.65, "万金属吨"),
        ("铜产品", 45.27, 26.01, 6.53, "万金属吨"),
        ("镍产品", 258.95, 19.70, 29.25, "万金属吨"),
        ("锂产品", 34.41, 20.65, 5.44, "万实物吨"),
        ("三元前驱体", 44.86, 16.84, 10.84, "万实物吨"),
        ("正极材料", 149.69, 9.36, 11.64, "万实物吨"),
        ("镍中间品", 117.81, 19.32, 23.65, "万金属吨"),
        ("贸易及其他", 97.09, 4.42, 0.0, "不适用"),
    ]
    for name, revenue, margin, shipment, shipment_unit in segments:
        facts.extend(
            [
                _fact(
                    "r-huayou-ar2025",
                    "huayou_integrated",
                    f"2025年{name}收入",
                    revenue,
                    "亿元人民币",
                    "2025",
                    f"huayou_2025_segment_{name}_revenue",
                    "按年报分产品主营业务口径；内部自供不另行叠加为合并收入。",
                    extraction_method="pdf_direct",
                ),
                _fact(
                    "r-huayou-ar2025",
                    "huayou_integrated",
                    f"2025年{name}毛利率",
                    margin,
                    "%",
                    "2025",
                    f"huayou_2025_segment_{name}_margin",
                    "按年报分产品收入和成本计算的毛利率。",
                    extraction_method="pdf_direct",
                ),
            ]
        )
        if shipment > 0:
            facts.append(
                _fact(
                    "r-huayou-ar2025",
                    "huayou_integrated",
                    f"2025年{name}销量或出货",
                    shipment,
                    shipment_unit,
                    "2025",
                    f"huayou_2025_segment_{name}_shipment",
                    "年报明确部分销量包含内部自供或加工口径，不能与对外收入机械相除得到ASP。",
                    extraction_method="pdf_direct",
                )
            )

    huayou_points = [
        ("r-huayou-ar2025", "2025年合并毛利润", 141.54, "亿元人民币", "2025", "huayou_gp_2025", "由营业收入减营业成本得到。"),
        ("r-huayou-ar2025", "2025年研发费用", 16.82, "亿元人民币", "2025", "huayou_rd_2025", "年报合并利润表口径。"),
        ("r-huayou-ar2025", "2025年财务费用", 23.99, "亿元人民币", "2025", "huayou_finance_cost_2025", "年报合并利润表口径。"),
        ("r-huayou-ar2025", "2025年投资收益", 9.34, "亿元人民币", "2025", "huayou_investment_income_2025", "其中权益法投资收益约5.18亿元。"),
        ("r-huayou-ar2025", "2025年少数股东损益", 14.10, "亿元人民币", "2025", "huayou_nci_profit_2025", "合并净利润与归母净利润之间的主要归属差额。"),
        ("r-huayou-ar2025", "2025年固定资产折旧", 45.30, "亿元人民币", "2025", "huayou_depreciation_2025", "现金流量表补充资料口径。"),
        ("r-huayou-ar2025", "2025年无形资产摊销", 4.71, "亿元人民币", "2025", "huayou_amortization_2025", "现金流量表补充资料口径。"),
        ("r-huayou-ar2025", "2025年存货增加造成的现金占用", 84.05, "亿元人民币", "2025", "huayou_inventory_cash_use_2025", "现金流量表补充资料以负数列示。"),
        ("r-huayou-ar2025", "2025年经营性应收增加造成的现金占用", 83.10, "亿元人民币", "2025", "huayou_receivable_cash_use_2025", "现金流量表补充资料以负数列示。"),
        ("r-huayou-ar2025", "2025年经营性应付增加带来的现金来源", 69.14, "亿元人民币", "2025", "huayou_payable_cash_source_2025", "现金流量表补充资料口径。"),
        ("r-huayou-ar2025", "2025年自由现金流", -67.46, "亿元人民币", "2025", "huayou_fcf_2025", "经营现金流40.12亿元减资本开支107.58亿元。"),
        ("r-huayou-ar2025", "2025年末资产负债率", 61.85, "%", "2025-12-31", "huayou_debt_ratio_2025", "总负债986.17亿元除以总资产1594.38亿元。"),
        ("r-huayou-ar2025", "2025年末流动比率", 0.95, "倍", "2025-12-31", "huayou_current_ratio_2025", "年报披露流动比率。"),
        ("r-huayou-ar2025", "2025年现金分红率", 15.52, "%", "2025", "huayou_payout_2025", "拟分红占归母净利润比例。"),
        ("r-huayou-q12026", "2026年第一季度营业收入", 258.04, "亿元人民币", "2026Q1", "huayou_revenue_2026q1", "一季报合并口径。"),
        ("r-huayou-q12026", "2026年第一季度归母净利润", 24.97, "亿元人民币", "2026Q1", "huayou_parent_ni_2026q1", "一季报合并口径。"),
        ("r-huayou-q12026", "2026年第一季度经营现金流", 11.75, "亿元人民币", "2026Q1", "huayou_ocf_2026q1", "一季报现金流量表口径。"),
        ("r-huayou-q12026", "2026年第一季度资本开支", 47.37, "亿元人民币", "2026Q1", "huayou_capex_2026q1", "购建固定资产、无形资产和其他长期资产支付的现金。"),
        ("r-huayou-q12026", "2026年第一季度自由现金流", -35.63, "亿元人民币", "2026Q1", "huayou_fcf_2026q1", "经营现金流11.75亿元减资本开支47.37亿元。"),
        ("r-huayou-q12026", "2026年第一季度末总资产", 1746.69, "亿元人民币", "2026Q1", "huayou_assets_2026q1", "一季报期末口径。"),
        ("r-huayou-q12026", "2026年第一季度末归母权益", 505.10, "亿元人民币", "2026Q1", "huayou_parent_equity_2026q1", "一季报期末口径。"),
        ("r-huayou-q12026", "2026年第一季度末存货", 303.11, "亿元人民币", "2026Q1", "huayou_inventory_2026q1", "一季报期末口径。"),
        ("r-huayou-q12026", "2026年第一季度末在建工程", 160.25, "亿元人民币", "2026Q1", "huayou_cip_2026q1", "一季报期末口径。"),
        ("r-huayou-ar2025", "华飞HPAL名义产能", 12.0, "万金属吨镍/年", "2025", "huafei_nameplate", "现有项目，不能再次作为增量叠加。"),
        ("r-huayou-ar2025", "华飞HPAL华友持股比例", 51.0, "%", "2025-12-31", "huafei_ownership", "少数股东损益必须在归母利润中扣除。"),
        ("r-huayou-ar2025", "华越HPAL名义产能", 6.0, "万金属吨镍/年", "2025", "huayue_nameplate", "现有项目，不能再次作为增量叠加。"),
        ("r-huayou-ar2025", "华越HPAL华友持股比例", 60.0, "%", "2025-12-31", "huayue_ownership", "2025年末由57%增至60%。"),
        ("r-huayou-ar2025", "前景锂业华友持股比例", 100.0, "%", "2025-12-31", "prospect_ownership", "2025年末由90%增至100%。"),
        ("r-huayou-ar2025", "华飞2025年营业收入", 144.95, "亿元人民币", "2025", "huafei_revenue_2025", "重要子公司披露口径。"),
        ("r-huayou-ar2025", "华飞2025年净利润", 12.52, "亿元人民币", "2025", "huafei_net_income_2025", "按51%持股粗略对应归母份额约6.39亿元，实际仍受合并抵销影响。"),
        ("r-huayou-ar2025", "华越2025年营业收入", 80.05, "亿元人民币", "2025", "huayue_revenue_2025", "重要子公司披露口径，年报该表未单列其净利润。"),
        ("w-vale-pomalaa", "Pomalaa HPAL镍名义产能", 12.0, "万金属吨镍/年", "规划", "pomalaa_nickel_nameplate", "项目仍在建设，不能按满产计入2026年利润。"),
        ("w-vale-pomalaa", "Pomalaa HPAL伴生钴名义产能", 1.5, "万金属吨钴/年", "规划", "pomalaa_cobalt_nameplate", "伴生钴产能与镍产能不可按实物吨相加。"),
        ("w-vale-pomalaa-progress", "Pomalaa矿山增长项目工程进度", 62.0, "%", "2026Q1", "pomalaa_mine_progress", "该进度不等同于HPAL整体完成度或商业产量。"),
        ("r-huayou-ar2025", "Sorowako HPAL镍名义产能", 6.0, "万金属吨镍/年", "规划", "sorowako_nickel_nameplate", "尚处建设准备和启动阶段，不进入2026—2028年基准利润。"),
        ("r-huayou-ar2025", "华星RKEF镍名义产能", 4.0, "万金属吨镍/年", "规划", "huaxing_rkef_nameplate", "已开工但不按名义产能计入当前产量。"),
        ("w-huayou-arcadia", "Arcadia年处理矿石能力", 450.0, "万吨矿石/年", "规划", "arcadia_ore_capacity", "矿石处理量不能直接写成碳酸锂当量产量。"),
        ("w-huayou-lithium", "津巴布韦硫酸锂项目名义产能", 5.0, "万吨硫酸锂/年", "规划", "zimbabwe_lithium_sulfate_capacity", "2026年4月首批发运，仍需观察稳定达产。"),
        ("w-sec-ewoyaa", "Atlantic Lithium收购现金对价", 2.10, "亿美元", "拟议", "ewoyaa_atlantic_price", "交易需审批与交割，不进入2026—2028年基准利润。"),
        ("w-sec-ewoyaa", "Elevra Ewoyaa权益收购现金对价", 0.71, "亿美元", "拟议", "ewoyaa_elevra_price", "交易需加纳监管审批，现金支出与项目利润分开。"),
        ("w-huayou-precursor", "印尼三元前驱体名义产能", 5.0, "万吨/年", "2025", "indonesia_precursor_capacity", "2025年进入规模生产，按实际爬坡进入材料业务。"),
        ("r-huayou-ar2025", "已锁定镍资源", 14.0, "亿湿吨矿石", "截至2025", "huayou_locked_nickel_resource", "湿吨矿石不是镍金属量，不能直接与产品销量比较。"),
        ("r-huayou-ar2025", "2025年MHP出货", 23.65, "万金属吨镍", "2025", "huayou_mhp_shipments_2025", "作为镍中间品经营规模指标。"),
        ("r-huayou-ar2025", "已锁定正极材料长期订单", 21.58, "万吨", "截至2025", "huayou_cathode_lta", "订单量不是单年收入，需按交付期和价格确认。"),
        ("r-huayou-ar2025", "已锁定前驱体长期订单", 15.56, "万吨", "截至2025", "huayou_precursor_lta", "订单量不是单年收入，需按交付期和价格确认。"),
    ]
    for source_ref, metric, value, unit, period, scope, note in huayou_points:
        facts.append(
            _fact(
                source_ref,
                "huayou_integrated",
                metric,
                value,
                unit,
                period,
                scope,
                note,
                extraction_method="inferred" if "自由现金流" in metric or "率" in metric and source_ref == "r-huayou-ar2025" else ("web_fetch" if source_ref.startswith("w-") else "pdf_direct"),
            )
        )

    nickel_points = [
        ("w-usgs-mcs2026", "2025年全球镍矿山产量", 3900, "千吨镍", "2025", "nickel_world_mine_2025", "USGS矿山产量。"),
        ("w-usgs-mcs2026", "2025年印尼镍矿山产量", 2600, "千吨镍", "2025", "nickel_indonesia_mine_2025", "约占全球三分之二。"),
        ("w-usgs-mcs2026", "2025年全球镍储量", 140000, "千吨镍", "2025", "nickel_world_reserves_2025", "USGS储量口径。"),
        ("w-usgs-mcs2026", "2025年印尼镍储量", 62000, "千吨镍", "2025", "nickel_indonesia_reserves_2025", "USGS储量口径。"),
        ("w-usgs-mcs2026", "2025年全球镍矿产量增速", 5.0, "%", "2025", "nickel_world_growth_2025", "USGS估算同比增速。"),
        ("w-usgs-mcs2026", "2025年印尼镍矿产量增速", 13.0, "%", "2025", "nickel_indonesia_growth_2025", "USGS估算同比增速。"),
        ("w-usgs-mcs2026", "2025年镍均价", 15000, "美元/吨", "2025", "nickel_average_price_2025", "USGS年度均价。"),
        ("w-usgs-mcs2026", "2024年镍均价", 16800, "美元/吨", "2024", "nickel_average_price_2024", "用于识别价格下行。"),
        ("w-usgs-mcs2026", "2022年全球原生镍过剩", 98.5, "千吨镍", "2022", "nickel_surplus_2022", "INSG历史市场余额。"),
        ("w-usgs-mcs2026", "2023年全球原生镍过剩", 170, "千吨镍", "2023", "nickel_surplus_2023", "INSG历史市场余额。"),
        ("w-usgs-mcs2026", "2024年全球原生镍过剩", 182, "千吨镍", "2024", "nickel_surplus_2024", "INSG历史市场余额。"),
        ("w-usgs-mcs2026", "2025年前九个月全球原生镍过剩", 189, "千吨镍", "2025M1-M9", "nickel_surplus_2025_9m", "INSG阶段性市场余额。"),
        ("w-indonesia-antara", "印尼2026年镍矿配额指引下限", 250, "百万湿吨矿石", "2026", "indonesia_rkab_2026_low", "官方表述的区间下限，不是镍金属量。"),
        ("w-indonesia-antara", "印尼2026年镍矿配额指引上限", 260, "百万湿吨矿石", "2026", "indonesia_rkab_2026_high", "官方表述的区间上限，企业仍可申请调整。"),
        ("w-indonesia-esdm", "印尼2026年RKAB最终决定状态", "2026年6月仍未最终决定", "状态", "2026-06-25", "indonesia_rkab_status", "防止把早期讨论值写成最终事实。"),
        ("w-iea-outlook-2026", "镍需求到2040年增长区间下限", 50, "%", "2025—2040", "iea_nickel_demand_growth_low", "IEA情景区间。"),
        ("w-iea-outlook-2026", "镍需求到2040年增长区间上限", 90, "%", "2025—2040", "iea_nickel_demand_growth_high", "IEA情景区间。"),
        ("w-iea-outlook-2026", "2035年镍基准供需判断", "轻微缺口，早期项目若按期投产可以填补", "判断", "2035", "iea_nickel_balance_2035", "不等于结构性长期短缺。"),
        ("w-iea-critical-2026", "2035年镍前三大矿山国集中度", 85, "%", "2035", "nickel_top3_concentration_2035", "IEA对集中度的长期判断。"),
        ("w-iea-critical-2026", "2024年镍前三大矿山国集中度", 75, "%", "2024", "nickel_top3_concentration_2024", "与2035年比较显示集中度上升。"),
        ("r-nickel-20260525", "2026年镍紧张情景余额", -3.2, "万吨镍", "2026", "nickel_tight_balance_2026_report", "报告情景而非已实现事实。"),
        ("r-nickel-20260525", "2026年镍宽松情景余额", 16.8, "万吨镍", "2026", "nickel_loose_balance_2026_report", "报告情景显示政策决定余额方向。"),
    ]
    for row in nickel_points:
        source_ref, metric, value, unit, period, scope, note = row
        facts.append(_fact(source_ref, "nickel_market", metric, value, unit, period, scope, note, extraction_method="pdf_direct" if source_ref.startswith("r-") else "web_fetch"))

    cobalt_points = [
        ("w-usgs-mcs2026", "2025年全球钴矿山产量", 310, "千吨钴", "2025", "cobalt_world_mine_2025", "USGS矿山产量。"),
        ("w-usgs-mcs2026", "2025年DRC钴矿山产量", 230, "千吨钴", "2025", "cobalt_drc_mine_2025", "约占全球73%。"),
        ("w-usgs-mcs2026", "2025年印尼钴矿山产量", 44, "千吨钴", "2025", "cobalt_indonesia_mine_2025", "主要来自镍HPAL伴生钴。"),
        ("w-usgs-mcs2026", "全球钴储量", 12000, "千吨钴", "2025", "cobalt_world_reserves", "USGS储量口径。"),
        ("w-usgs-mcs2026", "DRC钴产量全球占比", 73, "%", "2025", "cobalt_drc_share", "高集中度使政策冲击非线性。"),
        ("w-usgs-mcs2026", "印尼钴产量全球占比", 14, "%", "2025", "cobalt_indonesia_share", "印尼成为第二大增量来源。"),
        ("w-drc-quota", "DRC 2026年钴出口总配额", 96.6, "千吨钴", "2026", "drc_quota_total_2026", "出口配额不是矿山产量。"),
        ("w-drc-quota", "DRC 2026年钴基础配额", 87.0, "千吨钴", "2026", "drc_quota_base_2026", "按月分配的基础配额。"),
        ("w-drc-quota", "DRC 2026年钴战略配额", 9.6, "千吨钴", "2026", "drc_quota_strategic_2026", "由ARECOMS控制的战略配额。"),
        ("w-drc-quota", "DRC 2025年10月钴出口配额", 3.625, "千吨钴", "2025-10", "drc_quota_oct2025", "配额制度实施首月。"),
        ("w-drc-quota", "DRC 2025年11月钴出口配额", 7.25, "千吨钴", "2025-11", "drc_quota_nov2025", "月度基础额度。"),
        ("w-drc-quota", "DRC 2025年12月钴出口配额", 7.25, "千吨钴", "2025-12", "drc_quota_dec2025", "月度基础额度。"),
        ("w-iea-outlook-2026", "2035年钴供应缺口", "在DRC配额持续的基准情景下超过需求的25%", "判断", "2035", "iea_cobalt_gap_2035", "政策情景而非无条件预测。"),
        ("w-iea-ev-2026", "2025年LFP全球电动车电池占比", 55, "%以上", "2025", "lfp_ev_share_2025", "降低单位钴需求强度。"),
        ("w-iea-ev-2026", "2025年LFP全球储能电池占比", 90, "%以上", "2025", "lfp_storage_share_2025", "储能增长对钴需求传导较弱。"),
        ("w-iea-ev-2026", "NMC721与NMC811钴含量", 10, "%左右（金属质量）", "2025", "nmc_high_nickel_cobalt_content", "高镍化降低单位钴用量。"),
        ("r-cobalt-20260616", "2026年钴有效供应", 22.5, "万吨钴", "2026", "cobalt_effective_supply_2026", "报告在配额、库存与非DRC供应后估算。"),
        ("r-cobalt-20260616", "2026年钴需求", 24.0, "万吨钴", "2026", "cobalt_demand_2026", "报告需求情景。"),
        ("r-cobalt-20260616", "2026年钴供需缺口", -1.5, "万吨钴", "2026", "cobalt_gap_2026", "有效供应减需求。"),
        ("r-cobalt-20260616", "2027年钴有效供应", 22.7, "万吨钴", "2027", "cobalt_effective_supply_2027", "报告情景而非已实现事实。"),
        ("r-cobalt-20260616", "2027年钴需求", 26.1, "万吨钴", "2027", "cobalt_demand_2027", "报告需求情景。"),
        ("r-cobalt-20260616", "2027年钴供需缺口", -3.4, "万吨钴", "2027", "cobalt_gap_2027", "有效供应减需求。"),
    ]
    for row in cobalt_points:
        source_ref, metric, value, unit, period, scope, note = row
        facts.append(_fact(source_ref, "cobalt_market", metric, value, unit, period, scope, note, extraction_method="pdf_direct" if source_ref.startswith("r-") else "web_fetch"))

    lithium_points = [
        ("w-usgs-mcs2026", "2025年全球锂矿山产量", 290, "千吨锂", "2025", "lithium_world_mine_2025", "USGS锂金属量口径。"),
        ("w-usgs-mcs2026", "2025年全球锂消费量", 263, "千吨锂", "2025", "lithium_world_consumption_2025", "USGS锂金属量口径。"),
        ("w-usgs-mcs2026", "2024年全球锂矿山产量", 222, "千吨锂", "2024", "lithium_world_mine_2024", "用于校验2025年供应增长。"),
        ("w-usgs-mcs2026", "2024年全球锂消费量", 220, "千吨锂", "2024", "lithium_world_consumption_2024", "用于校验2025年需求增长。"),
        ("w-usgs-mcs2026", "2025年全球锂矿山产量增速", 31, "%", "2025", "lithium_supply_growth_2025", "供应增速快于需求。"),
        ("w-usgs-mcs2026", "2025年全球锂需求增速", 20, "%", "2025", "lithium_demand_growth_2025", "仍保持较快增长。"),
        ("w-usgs-mcs2026", "电池占锂终端用途比例", 88, "%", "2025", "lithium_battery_end_use_share", "需求高度依赖电池。"),
        ("w-usgs-mcs2026", "2025年碳酸锂平均价格", 9000, "美元/吨", "2025", "lithium_carbonate_average_price_2025", "USGS年度均价。"),
        ("w-usgs-mcs2026", "2025年1月中国碳酸锂现货价", 9300, "美元/吨", "2025-01", "china_lithium_price_jan2025", "USGS折算价格。"),
        ("w-usgs-mcs2026", "2025年11月中国碳酸锂现货价", 10300, "美元/吨", "2025-11", "china_lithium_price_nov2025", "USGS折算价格。"),
        ("w-usgs-mcs2026", "2025年澳大利亚锂矿产量", 92, "千吨锂", "2025", "lithium_australia_2025", "USGS国家产量。"),
        ("w-usgs-mcs2026", "2025年中国锂矿产量", 62, "千吨锂", "2025", "lithium_china_2025", "USGS国家产量。"),
        ("w-usgs-mcs2026", "2025年智利锂矿产量", 56, "千吨锂", "2025", "lithium_chile_2025", "USGS国家产量。"),
        ("w-usgs-mcs2026", "2025年津巴布韦锂矿产量", 28, "千吨锂", "2025", "lithium_zimbabwe_2025", "USGS国家产量。"),
        ("w-usgs-mcs2026", "2025年阿根廷锂矿产量", 23, "千吨锂", "2025", "lithium_argentina_2025", "USGS国家产量。"),
        ("w-iea-market-2026", "近两年锂需求年均增速", 25, "%左右", "2024—2025", "iea_lithium_demand_recent", "IEA市场概览。"),
        ("w-iea-outlook-2026", "锂需求到2040年增长倍数", 3, "倍以上", "2025—2040", "iea_lithium_demand_2040", "IEA既定政策情景。"),
        ("w-iea-market-2026", "2025年锂公司投资降幅", 40, "%左右", "2025", "lithium_investment_decline_2025", "低价压缩项目投资。"),
        ("w-iea-market-2026", "2025年锂与镍勘探支出降幅", 40, "%左右", "2025", "lithium_nickel_exploration_decline", "提高远期供应响应不确定性。"),
        ("r-lithium-20260614", "2026年全球锂供应", 225, "万吨碳酸锂当量", "2026", "lithium_supply_2026_report", "报告同口径情景。"),
        ("r-lithium-20260614", "2026年全球锂需求", 216, "万吨碳酸锂当量", "2026", "lithium_demand_2026_report", "报告同口径情景。"),
        ("r-lithium-20260614", "2026年全球锂供需余额", 9, "万吨碳酸锂当量", "2026", "lithium_balance_2026_report", "仍为小幅宽松。"),
        ("r-lithium-20260614", "2027年全球锂供应", 261, "万吨碳酸锂当量", "2027", "lithium_supply_2027_report", "报告同口径情景。"),
        ("r-lithium-20260614", "2027年全球锂需求", 270, "万吨碳酸锂当量", "2027", "lithium_demand_2027_report", "报告同口径情景。"),
        ("r-lithium-20260614", "2027年全球锂供需余额", -9, "万吨碳酸锂当量", "2027", "lithium_balance_2027_report", "由宽松转为小幅缺口。"),
        ("r-lithium-20260614", "2028年全球锂供应", 302, "万吨碳酸锂当量", "2028", "lithium_supply_2028_report", "报告同口径情景。"),
        ("r-lithium-20260614", "2028年全球锂需求", 334, "万吨碳酸锂当量", "2028", "lithium_demand_2028_report", "报告同口径情景。"),
        ("r-lithium-20260614", "2028年全球锂供需余额", -32, "万吨碳酸锂当量", "2028", "lithium_balance_2028_report", "缺口扩大但会刺激项目响应。"),
    ]
    for row in lithium_points:
        source_ref, metric, value, unit, period, scope, note = row
        facts.append(_fact(source_ref, "lithium_market", metric, value, unit, period, scope, note, extraction_method="pdf_direct" if source_ref.startswith("r-") else "web_fetch"))

    model_points = [
        ("nickel_market", "镍基准情景2030年供需余额", 80, "千吨镍", "2030", "run14_nickel_base_2030", "研究情景，不是外部事实。"),
        ("cobalt_market", "钴基准情景2030年供需余额", -6, "千吨钴", "2030", "run14_cobalt_base_2030", "研究情景，不是外部事实。"),
        ("lithium_market", "锂基准情景2030年供需余额", -400, "千吨碳酸锂当量", "2030", "run14_lithium_base_2030", "研究情景，不是外部事实。"),
    ]
    for entity_key, metric, value, unit, period, scope, note in model_points:
        facts.append(_fact("r-model-supply-demand", entity_key, metric, value, unit, period, scope, note, extraction_method="inferred"))

    financial_model_points = [
        ("2026年基准收入", 958.0, "亿元人民币", "2026", "run14_revenue_2026"),
        ("2027年基准收入", 1083.0, "亿元人民币", "2027", "run14_revenue_2027"),
        ("2028年基准收入", 1228.0, "亿元人民币", "2028", "run14_revenue_2028"),
        ("2026年基准归母净利润", 88.2, "亿元人民币", "2026", "run14_profit_2026"),
        ("2027年基准归母净利润", 105.6, "亿元人民币", "2027", "run14_profit_2027"),
        ("2028年基准归母净利润", 123.4, "亿元人民币", "2028", "run14_profit_2028"),
        ("2026年基准自由现金流", -36.1, "亿元人民币", "2026", "run14_fcf_2026"),
        ("2027年基准自由现金流", 26.3, "亿元人民币", "2027", "run14_fcf_2027"),
        ("2028年基准自由现金流", 79.5, "亿元人民币", "2028", "run14_fcf_2028"),
        ("独立估值核心股价下限", 41.14, "元/股", "2026-07-23", "run14_value_low"),
        ("独立估值核心股价上限", 51.24, "元/股", "2026-07-23", "run14_value_high"),
        ("市场隐含2026年市盈率", 8.92, "倍", "2026-07-23", "run14_market_implied_pe"),
        ("市场PB隐含ROE", 16.72, "%", "2026-07-23", "run14_market_implied_roe"),
    ]
    for metric, value, unit, period, scope in financial_model_points:
        facts.append(_fact("r-model-financial", "huayou_integrated", metric, value, unit, period, scope, "本研究独立模型输出，输入与输出哈希冻结。", extraction_method="inferred"))
    return facts


def build_data_points() -> list[dict[str, Any]]:
    sources = {row["ref"]: row for row in SOURCES}
    rows: list[dict[str, Any]] = []
    for index, spec in enumerate(build_fact_specs(), start=1):
        source = sources[spec["source_ref"]]
        point: dict[str, Any] = {
            "data_point_key": f"run14.huayou.{index:03d}",
            "source_ref": spec["source_ref"],
            "entity_key": spec["entity_key"],
            "metric": spec["metric"],
            "unit": spec["unit"],
            "period": spec["period"],
            "scope_key": spec["scope_key"],
            "source_excerpt": source["excerpt"],
            "extraction_method": spec["extraction_method"],
            "note": spec["note"],
        }
        if source["language"].startswith("en"):
            point["source_excerpt_zh"] = source["excerpt_zh"]
        if spec.get("observations"):
            point["observations"] = spec["observations"]
            point["value_text"] = str(spec["value"])
        elif isinstance(spec["value"], (int, float)):
            point["value_num"] = spec["value"]
            point["value_text"] = str(spec["value"])
        else:
            point["value_text"] = str(spec["value"])
        rows.append(point)
    return rows


def build_claims() -> list[dict[str, Any]]:
    specs = [
        ("huayou_integrated", "r-huayou-ar2025", "事实", "华友钴业2025年收入、利润与主要产品出货均增长，但经营现金流显著低于净利润且资本开支重新上升。"),
        ("huayou_integrated", "r-huayou-q12026", "事实", "华友钴业2026年第一季度盈利继续增长，但自由现金流仍为负，说明扩张期现金流约束没有消失。"),
        ("huayou_integrated", "r-huayou-ar2025", "分析", "镍产品与镍中间品贡献公司最大资源业务毛利润；钴和锂提供更高价格弹性，下游材料则提供客户与一体化协同。"),
        ("huayou_integrated", "w-vale-pomalaa", "事实", "Pomalaa 12万吨HPAL仍在建设，不能把名义产能当作2026年实际产量或上市公司全额权益量。"),
        ("huayou_integrated", "w-huayou-lithium", "事实", "津巴布韦硫酸锂项目已在2026年4月完成首批发运，从建设调试进入生产爬坡。"),
        ("huayou_integrated", "w-sec-ewoyaa", "事实", "Ewoyaa相关收购仍需审批和交割，当前只构成远期资源选择权和潜在现金支出。"),
        ("nickel_market", "w-usgs-mcs2026", "事实", "印尼约占2025年全球镍矿山产量三分之二，全球供给方向高度受印尼政策、矿石和项目爬坡影响。"),
        ("nickel_market", "w-indonesia-esdm", "反证", "印尼主管部门曾明确2026年RKAB总量尚未最终决定，早期配额数字不能写成不可改变的事实。"),
        ("nickel_market", "w-iea-outlook-2026", "结论", "镍的基准判断接近平衡而非结构性长期短缺；早期项目若落地，可能填补轻微缺口。"),
        ("cobalt_market", "w-drc-quota", "事实", "DRC 2026年钴出口配额为9.66万吨，显著低于其2025年矿山产量，政策改变了有效供应而非矿体储量。"),
        ("cobalt_market", "w-iea-outlook-2026", "结论", "若DRC配额持续，钴在中长期可能出现较大缺口，但LFP与低钴化学体系限制需求上行斜率。"),
        ("cobalt_market", "w-iea-ev-2026", "反证", "LFP已占电动车和储能电池较高份额，不能只凭电池总需求增长线性外推钴需求。"),
        ("lithium_market", "w-usgs-mcs2026", "事实", "2025年锂矿山供应增长快于消费增长，解释了近端仍可能宽松。"),
        ("lithium_market", "w-iea-market-2026", "结论", "需求快速增长与投资、勘探下滑同时存在，使锂市场从近端宽松转向中期缺口的风险上升。"),
        ("lithium_market", "r-lithium-20260614", "分析", "本地报告的同口径情景显示2026年小幅宽松、2027年转缺口、2028年缺口扩大，但价格反弹会重新激活供给。"),
        ("huayou_integrated", "r-model-financial", "推断", "独立模型预计2026—2028年归母净利润为88.2、105.6和123.4亿元，2026年自由现金流仍为负。"),
        ("huayou_integrated", "r-model-financial", "估值", "市盈率、PB—ROE和EV/EBITDA的交叉区间对应约41.14—51.24元/股，当前价格接近区间下沿。"),
    ]
    sources = {row["ref"]: row for row in SOURCES}
    claims: list[dict[str, Any]] = []
    for index, (entity, ref, claim_type, text) in enumerate(specs, start=1):
        source = sources[ref]
        row: dict[str, Any] = {
            "claim_id": f"run14.claim.{index:03d}",
            "entity_key": entity,
            "source_ref": ref,
            "claim_type": claim_type,
            "claim_text": text,
            "source_excerpt": source["excerpt"],
        }
        if source["language"].startswith("en"):
            row["source_excerpt_zh"] = source["excerpt_zh"]
        claims.append(row)
    return claims
