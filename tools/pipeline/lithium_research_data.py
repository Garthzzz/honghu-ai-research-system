from __future__ import annotations

"""Shared evidence ledger for the independent lithium and carbonate industries.

Supplier financial observations are intentionally absent.  Company market,
actual financials, consensus and frozen internal forecasts live in
``financial.db``; this module carries industry, project, production, policy and
model-input facts for the two B-track research libraries.
"""

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = (
    ROOT / "cache/lithium_research/models/lithium_company_independent_models_v1.json"
)
LITHIUM_SD_PATH = (
    ROOT / "cache/lithium_research/models/lithium_supply_demand_model_v1.json"
)
CARBONATE_SD_PATH = (
    ROOT / "cache/lithium_research/models/carbonate_supply_demand_model_v1.json"
)


def _source(
    ref: str,
    *,
    title: str,
    publisher: str,
    date: str,
    file: str | None = None,
    url: str | None = None,
    tier: int = 1,
    language: str = "zh",
    primary: bool = True,
    channel: str = "web",
    rationale: str,
) -> dict[str, Any]:
    return {
        "source_ref": ref,
        "source_file": file,
        "source_url": url,
        "title": title,
        "publisher": publisher,
        "publish_date": date,
        "source_type": (
            "公告" if file and "年度报告" in title
            else "协会数据" if primary
            else "研究报告"
        ),
        "quality_tier": tier,
        "source_channel": channel,
        "language": language,
        "fetch_method": "pdf_local" if file else "web_fetch",
        "is_primary_source": primary,
        "source_credibility": (
            "audited_company_filing"
            if file and "年度报告" in title
            else "official_or_primary"
            if primary
            else "sell_side_research"
        ),
        "independence_key": ref,
        "independence_rationale": rationale,
    }


SOURCE_SPECS: list[dict[str, Any]] = [
    _source(
        "usgs_mcs_2026",
        title="USGS《Mineral Commodity Summaries 2026》",
        publisher="U.S. Geological Survey",
        date="2026-02-06",
        file="official_global/2026_USGS_Mineral_Commodity_Summaries.pdf",
        language="en",
        channel="report",
        rationale="美国地质调查局对2025年全球锂产量、消费、用途、储量和资源量的官方统计。",
    ),
    _source(
        "iea_gcm_2026",
        title="IEA《Global Critical Minerals Outlook 2026》",
        publisher="International Energy Agency",
        date="2026-07-16",
        url="https://www.iea.org/reports/global-critical-minerals-outlook-2026",
        language="en",
        rationale="IEA对锂需求、供应投资、集中度和2035年前项目平衡的独立模型。",
    ),
    _source(
        "australia_req_202606",
        title="Resources and Energy Quarterly, June 2026",
        publisher="Australian Government Department of Industry",
        date="2026-06-30",
        url="https://www.industry.gov.au/publications/resources-and-energy-quarterly-june-2026",
        language="en",
        rationale="澳大利亚政府对本国锂矿产量、全球供需和出口收入的季度预测。",
    ),
    _source(
        "sqm_20f_2025",
        title="SQM 2025 Form 20-F",
        publisher="SQM / U.S. SEC",
        date="2026-04-24",
        url="https://www.sec.gov/Archives/edgar/data/909037/000090903726000023/sqm-20251231.htm",
        language="en",
        rationale="SQM向美国证监会提交的年度报告及其2025年全球锂化学品企业份额估计。",
    ),
    _source(
        "rio_rincon_202603",
        title="Rio Tinto secures financing for the Rincon lithium project",
        publisher="Rio Tinto",
        date="2026-03-11",
        url=(
            "https://www.riotinto.com/news/releases/2026/"
            "rio-tinto-secures-1-175-billion-financing-package-for-rincon-lithium-project-in-argentina"
        ),
        language="en",
        rationale=(
            "Rio Tinto披露Rincon总投资、融资、6万吨电池级碳酸锂目标、"
            "2028年首产和三年爬坡。"
        ),
    ),
    _source(
        "rio_q1_2026",
        title="Rio Tinto first quarter 2026 production results",
        publisher="Rio Tinto",
        date="2026-04-21",
        url=(
            "https://www.riotinto.com/en/news/releases/2026/"
            "rio-tinto-releases-first-quarter-2026-production-results"
        ),
        language="en",
        rationale="Rio Tinto披露Arcadium锂产量、Fenix 1B与Sal de Vida机械完工和首产进度。",
    ),
    _source(
        "albemarle_kemerton_202602",
        title="Albemarle to idle Kemerton Train 1",
        publisher="Albemarle",
        date="2026-02-11",
        url=(
            "https://www.albemarle.com/us/en/news/"
            "albemarle-announces-plans-to-idle-its-kemerton-lithium-hydroxide-processing-plant-a"
        ),
        language="en",
        rationale=(
            "Albemarle披露Kemerton剩余产线停产维护，显示矿端资源与海外"
            "氢氧化锂加工经济性不能视为同一壁垒。"
        ),
    ),
    _source(
        "igo_greenbushes_2026q1",
        title="IGO March 2026 Quarterly Activities Report",
        publisher="IGO",
        date="2026-04-28",
        url=(
            "https://www.igo.com.au/site/pdf/"
            "eea2bbe7-923b-47be-86f7-ef3505bb2479/Platform/ListPage/"
            "March-2026-Quarterly-Activities-Report.pdf"
        ),
        language="en",
        rationale=(
            "Greenbushes季度产量、售价、现金成本、CGP3爬坡和资本开支的"
            "合资方一手披露。"
        ),
    ),
    _source(
        "pls_pilgangoora_2026",
        title="Pilgangoora operation and P2000 expansion",
        publisher="PLS",
        date="2026-06-19",
        url="https://pls.com/our-projects/pilgangoora-operation/expansion/",
        language="en",
        rationale=(
            "PLS披露Pilgangoora扩建可研、潜在200万吨精矿能力和投资纪律；"
            "规划产能不进入基准供给。"
        ),
    ),
    _source(
        "albemarle_10k_2025",
        title="Albemarle 2025 Form 10-K",
        publisher="Albemarle / U.S. SEC",
        date="2026-02-25",
        url="https://www.sec.gov/Archives/edgar/data/915913/000091591326000018/alb-20251231.htm",
        language="en",
        rationale=(
            "Albemarle向美国证监会提交的年度报告，披露按权益计算的Greenbushes、"
            "Wodgina、Salar de Atacama与Silver Peak锂金属产量及分部财务。"
        ),
    ),
    _source(
        "rio_annual_2025",
        title="Rio Tinto 2025 Annual Report",
        publisher="Rio Tinto",
        date="2026-02-19",
        url="https://www.riotinto.com/en/invest/reports/annual-report",
        language="en",
        rationale=(
            "Rio Tinto年度报告披露收购Arcadium后的权益LCE产量、项目资本开支、"
            "自由现金流和向2028年20万吨级能力扩张的经营边界。"
        ),
    ),
    _source(
        "pls_annual_2025",
        title="PLS 2025 Annual Report",
        publisher="PLS",
        date="2025-08-25",
        url=(
            "https://www.pls.com/storage/announcements/"
            "2025-annual-report-incorporating-appendix-4e-2025-08-25.pdf"
        ),
        language="en",
        rationale=(
            "PLS年度报告披露Pilgangoora实际精矿产量、品位、单位成本与扩建进度，"
            "用于区分已投产供给和P2000远期选项。"
        ),
    ),
    _source(
        "igo_annual_2025",
        title="IGO 2025 Annual Report",
        publisher="IGO",
        date="2025-08-28",
        url=(
            "https://www.igo.com.au/site/PDF/"
            "c0f122e3-3d34-4858-867f-76762acc6212/IGOAnnualReport2025printable"
        ),
        language="en",
        rationale=(
            "IGO以合资方身份披露Greenbushes的100%口径精矿产量、现金成本、"
            "股权结构和Kwinana经营表现。"
        ),
    ),
    _source(
        "minres_annual_2025",
        title="Mineral Resources 2025 Annual Report and operating data",
        publisher="Mineral Resources",
        date="2025-08-28",
        url="https://reports.mineralresources.com.au/2025-annual-report/index.html",
        language="en",
        rationale=(
            "Mineral Resources披露Mt Marion与Wodgina的权益精矿出货、成本和"
            "运营状态，补齐澳大利亚非Greenbushes供给。"
        ),
    ),
    _source(
        "liontown_annual_2025",
        title="Liontown FY2025 Annual Report",
        publisher="Liontown",
        date="2025-09-24",
        url="https://www.liontown.com/wp-content/uploads/2025/09/61285793.pdf",
        language="en",
        rationale=(
            "Liontown年度报告披露Kathleen Valley投产首年的精矿产量、品位、"
            "回收率与地下矿爬坡。"
        ),
    ),
    _source(
        "core_annual_2025",
        title="Core Lithium 2025 Annual Report",
        publisher="Core Lithium",
        date="2025-09-26",
        url="https://corelithium.com.au/announcements/7165466",
        language="en",
        rationale=(
            "Core Lithium年度报告披露Finniss停产维护、重启研究的产量、成本、"
            "资本开支和矿山寿命，作为锂价下行导致供给退出的反例。"
        ),
    ),
    _source(
        "canada_lithium_facts_2026",
        title="Lithium facts",
        publisher="Natural Resources Canada",
        date="2026-02-27",
        url=(
            "https://natural-resources.canada.ca/minerals-mining/"
            "mining-data-statistics-analysis/minerals-metals-facts/lithium-facts"
        ),
        language="en",
        rationale=(
            "加拿大自然资源部披露2024年国家锂产量、在产矿山和北美项目进展，"
            "用于核验USGS以外的加拿大供给。"
        ),
    ),
    _source(
        "us_doe_thacker_pass",
        title="Thacker Pass project summary",
        publisher="U.S. Department of Energy",
        date="2024-10-28",
        url="https://www.energy.gov/edf/thacker-pass",
        language="en",
        rationale=(
            "美国能源部披露Thacker Pass贷款规模、一期电池级碳酸锂目标与建设"
            "就业，是北美政策支持和项目融资的一手资料。"
        ),
    ),
    _source(
        "chile_national_lithium_strategy",
        title="Chile Advances with Lithium: National Lithium Strategy",
        publisher="Government of Chile",
        date="2024-03-26",
        url=(
            "https://www.gob.cl/en/news/"
            "chile-advances-with-lithium-these-are-the-main-definitions-of-the-national-strategy/"
        ),
        language="en",
        rationale=(
            "智利政府明确Atacama与Maricunga由国有企业取得多数参与、保护盐湖"
            "和公私合作安排，用于把资源治理传导到权益与终值。"
        ),
    ),
    _source(
        "argentina_rigi_rincon_2025",
        title="Resolución 735/2025: Rincon加入RIGI",
        publisher="Argentina.gob.ar",
        date="2025-06-03",
        url="https://www.argentina.gob.ar/normativa/nacional/norma-413550",
        language="es",
        rationale=(
            "阿根廷官方批准Rincon作为长期战略出口项目加入RIGI，并披露"
            "5.3万吨初始和6万吨远期电池级碳酸锂能力。"
        ),
    ),
    _source(
        "mali_goulamina_agreement_2024",
        title="Goulamina锂项目重新谈判协议",
        publisher="Mali Ministry of Mines",
        date="2024-07-24",
        url=(
            "https://www.mines.gouv.ml/"
            "signature-de-laccord-sur-le-projet-de-lithium-de-goulamina-et-la-mine-de-morila"
        ),
        language="fr",
        rationale=(
            "马里政府披露依据2023矿业法将国家与本地权益由20%提高到35%，"
            "直接约束赣锋对Goulamina的穿透权益和现金分配。"
        ),
    ),
    _source(
        "bolivia_dle_contracts_2025",
        title="Bolivia DLE lithium contracts",
        publisher="Yacimientos de Litio Bolivianos",
        date="2025-07-03",
        url=(
            "https://www.ylb.gob.bo/index.php/nota_prensa/"
            "ministro-gallardo-expone-en-diputados-alcances-del-contrato-entre-ylb-y-cbc-para-industrializar-litio-en-uyuni/"
        ),
        language="es",
        rationale=(
            "玻利维亚国有锂业公司披露中国CBC两座DLE工厂的投资与1万、2.5万吨"
            "名义产能，用于区分合同产能和现有极低实际产量。"
        ),
    ),
    _source(
        "mexico_litiomx_2025",
        title="Litio para México职责与组织",
        publisher="Government of Mexico / LitioMx",
        date="2025-05-19",
        url="https://www.gob.mx/litiomx/que-hacemos",
        language="es",
        rationale=(
            "墨西哥政府说明由LitioMx负责境内锂的勘探、开采、选冶和价值链控制，"
            "用于判断资源国有化对项目可投资性的影响。"
        ),
    ),
    _source(
        "australia_cmpti_2026",
        title="Critical Minerals Production Tax Incentive",
        publisher="Australian Government Department of Industry",
        date="2026-07-20",
        url=(
            "https://www.industry.gov.au/mining-oil-and-gas/minerals/"
            "critical-minerals/critical-minerals-production-tax-incentive"
        ),
        language="en",
        rationale=(
            "澳大利亚政府明确2027年起合格关键矿物加工成本可获10%税收抵免，"
            "但采矿、选矿、资本开支和原料成本不在适用范围。"
        ),
    ),
    _source(
        "miit_lithium_2026q1",
        title="2026年一季度有色金属行业运行情况",
        publisher="工业和信息化部",
        date="2026-05-08",
        url="https://wap.miit.gov.cn/jgsj/ycls/ysjs/art/2026/art_e7f7db9f5d394eb98f27d9dbde0e6592.html",
        rationale="中国工信部披露2026年一季度碳酸锂价格与进口变化。",
    ),
    _source(
        "argentina_mining_2025",
        title="Argentina mining exports reached a record in 2025",
        publisher="Argentina.gob.ar",
        date="2026-01-19",
        url="https://www.argentina.gob.ar/node/489874",
        language="es",
        rationale="阿根廷政府披露2025年矿业及锂出口和在产矿山数量。",
    ),
    _source(
        "chile_maricunga_202602",
        title="Chile signs the Maricunga lithium CEOL",
        publisher="Ministerio de Minería de Chile",
        date="2026-02-12",
        url="https://www.minmineria.gob.cl/?noticia=estrategia-nacional-del-litio-da-nuevo-paso-con-firma-de-segundo-ceol-para-operacion-de-litio-en-la-region-de-atacama",
        language="es",
        rationale="智利矿业部披露Maricunga合同、国有主导和项目时间安排。",
    ),
    _source(
        "zimbabwe_export_202602",
        title="Press Statement on Mineral and Lithium Concentrate Exports",
        publisher="Zimbabwe Ministry of Mines",
        date="2026-02-13",
        url="https://www.mines.gov.zw/wp-content/uploads/2026/02/PRESS-STATEMENT-ON-EXPORTS-1.pdf",
        language="en",
        rationale="津巴布韦政府原始出口政策声明。",
    ),
    _source(
        "mali_lithium_2026",
        title="Les mines de lithium de Bougouni",
        publisher="Mali Ministry of Mines",
        date="2026-04-02",
        url="https://mines.gouv.ml/les-mines-de-lithium-de-bougouni-le-mali-renforce-son-positionnement-dans-le-cercle-ferme-des-pays",
        language="fr",
        rationale="马里政府披露两座锂矿2026年精矿计划和Goulamina国家权益。",
    ),
    _source(
        "bolivia_ylb_2026",
        title="YLB plans 3,600 tonnes of lithium carbonate in 2026",
        publisher="Yacimientos de Litio Bolivianos",
        date="2026-02-03",
        url="https://www.ylb.gob.bo/index.php/nota_prensa/20656/",
        language="es",
        rationale="玻利维亚国有锂业公司披露2026年碳酸锂产量目标。",
    ),
    _source(
        "nigeria_lithium_plant",
        title="Nigeria commissions a lithium processing plant",
        publisher="Federal Ministry of Information and National Orientation",
        date="2026-05-10",
        url="https://fmino.gov.ng/president-tinubu-commissions-6-000-metric-tons-per-day-lithium-processing-plant-in-nasarawa-state/",
        language="en",
        rationale="尼日利亚政府披露加工厂原矿处理规模；不把处理量转换成LCE。",
    ),
    _source(
        "cnfin_carbonate_2026h1",
        title="2026年上半年碳酸锂产量与库存变化",
        publisher="中国金融信息网",
        date="2026-07-02",
        url="https://www.cnfin.com/dz-lb/detail/20260702/4434699_1.html",
        tier=2,
        primary=False,
        rationale="转述Mysteel上半年产量口径，用于与SMM覆盖范围对账，不作为单一事实源。",
    ),
    _source(
        "cnmn_carbonate_2026h1",
        title="碳酸锂产量与库存样本变化",
        publisher="中国有色金属报",
        date="2026-07-08",
        url="https://www.cnmn.com.cn/ShowNews1.aspx?id=471111",
        tier=2,
        primary=False,
        rationale="转述SMM统计，保留样本扩容说明，与Mysteel口径不机械平均。",
    ),
    _source(
        "lithium_association_2025",
        title="2025年我国基础锂盐产量与进出口",
        publisher="中国有色金属工业协会锂业分会",
        date="2026-02-12",
        url="https://xny.mysteel.com/a/26021213/96D992D18EA41362.html",
        tier=2,
        primary=False,
        rationale=(
            "锂业分会年度统计的公开转载，披露碳酸锂、氢氧化锂和氯化锂产能产量；"
            "柔性产线和产品互转未重复统计。"
        ),
    ),
    _source(
        "lithium_association_2025_competition",
        title="2025年中国锂盐生产企业结构",
        publisher="中国有色金属工业协会锂业分会",
        date="2026-03-24",
        url="https://www.itdcw.com/news/hangyefenxi/03241545542026.html",
        tier=2,
        primary=False,
        rationale=(
            "锂业分会年度会议数据的公开转载，披露万吨级企业数量及碳酸锂、"
            "氢氧化锂前五企业身份，不提供无法核验的单企份额。"
        ),
    ),
    _source(
        "lithium_association_2025h1",
        title="2025年6月及上半年锂行业运行情况",
        publisher="中国有色金属工业协会锂业分会",
        date="2025-07-23",
        url="https://www.cnmn.com.cn/ShowNews1.aspx?id=463753",
        rationale="锂业分会披露上半年基础锂盐产量、碳酸锂CR10和前三企业身份。",
    ),
    _source(
        "smm_carbonate_2026h1",
        title="2026年上半年碳酸锂市场复盘与下半年展望",
        publisher="上海有色网（SMM）",
        date="2026-07-16",
        url="https://new-energy.smm.cn/content/14042/103999601",
        tier=2,
        primary=False,
        rationale=(
            "SMM高频样本披露上半年产量、月度需求起止点和下半年供需判断；"
            "用于市场运行跟踪，不替代政府或海关事实。"
        ),
    ),
    _source(
        "smm_customs_carbonate_2026h1",
        title="2026年6月及上半年中国碳酸锂进出口",
        publisher="上海有色网（海关数据转述）",
        date="2026-07-21",
        url="https://news.smm.cn/live/detail/104013273",
        tier=2,
        primary=False,
        rationale="逐月海关数据转述，披露上半年进口、出口和六月单月值。",
    ),
    _source(
        "dongwu_carbonate_20260226",
        title="碳酸锂行业专题：需求超预期，开启2026—2027年向上新周期",
        publisher="东吴证券",
        date="2026-02-26",
        file="20260226-东吴证券-碳酸锂行业专题：需求超预期，开启26_27年向上新周期.pdf",
        primary=False,
        channel="report",
        rationale="卖方供需平衡和项目表，作为外部情景对照。",
    ),
    _source(
        "zheshang_lithium_20260614",
        title="碳酸锂行业深度：供需紧平衡趋势强化",
        publisher="浙商证券",
        date="2026-06-14",
        file="20260614-浙商证券-碳酸锂行业深度报告：供需紧平衡趋势强化，价格中枢有望抬升 (1).pdf",
        primary=False,
        channel="report",
        rationale="卖方国家供给、需求分项和2026—2028供需预测，作为情景对照。",
    ),
    _source(
        "dongfang_lithium_20260222",
        title="2026年锂行业策略：锂矿二次迸发大时代",
        publisher="东方证券",
        date="2026-02-22",
        file="20260222-东方证券-2026年锂行业策略：如日之升，锂矿二次迸发大时代.pdf",
        primary=False,
        channel="report",
        rationale="卖方锂资源项目、成本和周期判断，用于第二条本地研报链。",
    ),
    _source(
        "dongbei_carbonate_20260519",
        title="碳酸锂行业深度：供需双击，新周期仍在途",
        publisher="东北证券",
        date="2026-05-19",
        file="20260519-东北证券-碳酸锂行业深度报告：供需双击，碳酸锂新周期仍在途.pdf",
        primary=False,
        channel="report",
        rationale="卖方碳酸锂价格、成本曲线和供需情景，用于外部对账。",
    ),
    _source(
        "haizheng_futures_20260724",
        title="强现实vs弱预期，碳酸锂低多需做好仓位管理",
        publisher="海证期货",
        date="2026-07-24",
        file="2026-07-24_海证期货_期货研究_强现实vs弱预期，碳酸锂低多需做好仓位管理.pdf",
        primary=False,
        channel="report",
        rationale="最新现货、期货、库存和交易结构观察，不替代产业供需事实。",
    ),
]


COMPANY_FILES = {
    "赣锋锂业": ("002460.SZ", "002460_赣锋锂业_2025年年度报告.pdf"),
    "融捷股份": ("002192.SZ", "002192_融捷股份_2025年年度报告.pdf"),
    "盛新锂能": ("002240.SZ", "002240_盛新锂能_2025年年度报告.pdf"),
    "盐湖股份": ("000792.SZ", "000792_盐湖股份_2025年年度报告.pdf"),
    "大中矿业": ("001203.SZ", "001203_大中矿业_2025年年度报告.pdf"),
    "雅化集团": ("002497.SZ", "002497_雅化集团_2025年年度报告.pdf"),
    "天华新能": ("300390.SZ", "300390_天华新能_2025年年度报告.pdf"),
    "天齐锂业": ("002466.SZ", "002466_天齐锂业_2025年年度报告.pdf"),
    "永杉锂业": ("603399.SH", "603399_永杉锂业_2025年年度报告.pdf"),
    "中矿资源": ("002738.SZ", "002738_中矿资源_2025年年度报告.pdf"),
    "藏格矿业": ("000408.SZ", "000408_藏格矿业_2025年年度报告.pdf"),
    "西藏城投": ("600773.SH", "600773_西藏城投_2025年年度报告.pdf"),
    "永兴材料": ("002756.SZ", "002756_永兴材料_2025年年度报告.pdf"),
}
for company, (ticker, filename) in COMPANY_FILES.items():
    ref = f"ar_{ticker.replace('.', '_')}_2025"
    SOURCE_SPECS.append(
        _source(
            ref,
            title=f"{company}2025年年度报告",
            publisher=company,
            date="2026-04-30",
            file=f"company_filings/{filename}",
            channel="report",
            rationale=f"{company}经交易所披露的年度报告；用于项目、产能、产量、权益和经营口径。",
        )
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
    source = next(row for row in SOURCE_SPECS if row["source_ref"] == source_ref)
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
            "inferred" if inferred
            else "web_fetch" if source.get("source_url")
            else "pdf_direct"
        ),
        "is_forecast": bool(forecast),
        "note": note,
        "scope_key": scope or metric,
    }


COMPANY_DIRECT_FACTS: dict[str, list[tuple[str, str, str, float]]] = {
    "赣锋锂业": [
        ("Cauchari-Olaroz公司权益", "%", "2025", 46.67),
        ("Cauchari-Olaroz碳酸锂产量", "万吨", "2025", 3.41),
        ("Goulamina公司权益", "%", "2025", 65.0),
        ("Goulamina干基锂精矿产量", "万吨", "2025", 33.66),
        ("Mariana氯化锂产能", "万吨/年", "2025", 2.0),
        ("四川赣锋锂盐项目产能", "万吨/年", "2026规划", 5.0),
    ],
    "融捷股份": [
        ("134号脉采矿能力", "万吨原矿/年", "2025", 105.0),
        ("锂矿选矿能力", "万吨原矿/年", "2025", 45.0),
        ("锂精矿产量", "万吨", "2025", 18.56),
        ("合并锂盐产能", "万吨/年", "2025", 0.3),
        ("联营锂盐产能", "万吨/年", "2025", 2.0),
        ("联营锂盐规划产能", "万吨/年", "规划", 4.0),
    ],
    "盛新锂能": [
        ("锂盐建成产能", "万吨/年", "2025", 13.7),
        ("锂金属建成产能", "万吨/年", "2025", 0.05),
        ("业隆沟锂精矿产能", "万吨/年", "2025", 7.5),
        ("Sabi Star锂精矿产能", "万吨/年", "2025", 29.0),
        ("木绒设计原矿处理能力", "万吨/年", "规划", 300.0),
    ],
    "盐湖股份": [
        ("原有碳酸锂设计产能", "万吨/年", "2025", 4.0),
        ("新增碳酸锂项目产能", "万吨/年", "试生产", 4.0),
        ("碳酸锂产量", "万吨", "2025", 4.65),
        ("碳酸锂销量", "万吨", "2025", 4.56),
    ],
    "大中矿业": [
        ("鸡脚山一期碳酸锂产能", "万吨/年", "2026目标", 2.0),
        ("加达锂矿首个贡献年份", "年", "计划", 2027.0),
    ],
    "雅化集团": [
        ("Kamativi锂精矿产能", "万吨/年", "2025", 35.0),
        ("李家沟锂精矿产能下限", "万吨/年", "2025", 18.0),
        ("李家沟锂精矿产能上限", "万吨/年", "2025", 20.0),
        ("锂盐设计产能", "万吨/年", "2025", 13.0),
    ],
    "天华新能": [
        ("锂盐建成产能", "万吨/年", "2025", 16.5),
        ("氢氧化锂产能", "万吨/年", "2025", 13.5),
        ("碳酸锂产能", "万吨/年", "2025", 3.0),
        ("氢氧化锂产量", "万吨", "2025", 5.95),
        ("碳酸锂产量", "万吨", "2025", 4.74),
        ("Ogapa经济权益", "%", "2025", 37.5),
    ],
    "天齐锂业": [
        ("Greenbushes锂精矿产能", "万吨/年", "2025", 214.0),
        ("Greenbushes锂精矿产量", "万吨", "2025", 135.0),
        ("Greenbushes化学级精矿产量", "万吨", "2025", 130.0),
        ("Greenbushes穿透权益", "%", "2025", 26.01),
    ],
    "永杉锂业": [
        ("碳酸锂产量", "万吨", "2025", 1.3814),
        ("氢氧化锂产量", "万吨", "2025", 1.4463),
        ("锂盐现有产能", "万吨/年", "2025", 4.5),
        ("锂盐在建扩产", "万吨/年", "2026目标", 2.2),
        ("扩产后锂盐产能下限", "万吨/年", "2026目标", 6.0),
    ],
    "中矿资源": [
        ("Bikita锂资源量", "万吨LCE", "2025", 343.41),
        ("选矿总能力", "万吨原矿/年", "2025", 418.0),
        ("锂盐产能", "万吨/年", "2025", 7.1),
        ("升级锂盐产线产能", "万吨/年", "2026", 3.0),
    ],
    "藏格矿业": [
        ("碳酸锂产量", "万吨", "2025", 0.8808),
        ("碳酸锂销量", "万吨", "2025", 0.8957),
        ("碳酸锂设计产能", "万吨/年", "2025", 1.0),
        ("Mamico碳酸锂项目产能", "万吨/年", "规划", 5.0),
        ("Mamico间接权益", "%", "规划", 26.95),
        ("钾肥产量", "万吨", "2025", 103.32),
    ],
    "西藏城投": [
        ("国能矿业权益", "%", "2025", 41.0),
        ("两盐湖锂资源量", "万吨LCE", "2025", 390.0),
        ("两盐湖规划碳酸锂产能", "万吨/年", "规划", 10.0),
    ],
    "永兴材料": [
        ("锂业务产量", "万吨", "2025", 2.4823),
    ],
}


def _build_industry_facts(industry: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if industry == "锂":
        official = [
            ("全球锂产量（不含美国）", "2025", "万吨锂", 29.0),
            ("全球锂消费量", "2025", "万吨锂", 26.3),
            ("电池占锂消费比例", "2025", "%", 88.0),
            ("全球锂产量折合LCE", "2025", "百万吨LCE", 1.544),
            ("全球锂消费折合LCE", "2025", "百万吨LCE", 1.400),
        ]
        for metric, period, unit, value in official:
            rows.append(
                _dp(
                    "usgs_mcs_2026",
                    metric,
                    period,
                    unit,
                    value,
                    "USGS 2026矿产品摘要披露2025年全球锂产量、消费与用途。",
                    inferred="折合LCE" in metric,
                    note=(
                        "按1吨锂金属约等于5.323吨LCE换算。"
                        if "折合LCE" in metric else ""
                    ),
                    scope=f"global_lithium_{metric}",
                )
            )
        rows.append(
            _dp(
                "iea_gcm_2026",
                "过去两年全球锂需求年均增速",
                "2024-2025",
                "%",
                25.0,
                "IEA 2026关键矿产展望称，过去两年锂需求平均每年增长约25%。",
                scope="global_lithium_recent_demand_growth",
            )
        )
        model = json.loads(LITHIUM_SD_PATH.read_text(encoding="utf-8"))
        for row in model["base_rows"]:
            for metric, key, inferred in (
                ("全球锂生产", "available_supply_mt_lce", False),
                ("全球锂需求", "demand_mt_lce", False),
                ("全球锂供需余额", "balance_mt_lce", True),
            ):
                rows.append(
                    _dp(
                        "australia_req_202606",
                        metric,
                        str(row["year"]),
                        "百万吨LCE",
                        row[key],
                        "澳大利亚政府2026年6月资源与能源季度报告的全球锂供需表。",
                        forecast=row["year"] >= 2026,
                        inferred=inferred,
                        note=(
                            "余额＝全球锂生产－全球锂需求；供给和需求为官方表原值。"
                            if inferred else
                            "严格沿用同一官方表口径，不与卖方宽口径序列拼接。"
                        ),
                        scope=f"global_lithium_official_{metric}",
                    )
                )
        country_ledger = model["country_mine_2025"]
        for country, value in country_ledger["rows"].items():
            rows.append(
                _dp(
                    "usgs_mcs_2026",
                    f"{country}锂矿产量",
                    "2025",
                    "千吨锂金属",
                    value,
                    "USGS 2026矿产品摘要的2025年国家矿山产量。",
                    scope=f"lithium_mine_country_{country}",
                )
            )
        for metric, value in (
            ("全球锂矿国家CR3", country_ledger["cr3_pct"]),
            ("全球锂矿国家CR5", country_ledger["cr5_pct"]),
        ):
            rows.append(
                _dp(
                    "usgs_mcs_2026",
                    metric,
                    "2025",
                    "%",
                    value,
                    "按USGS国家矿山产量与世界29万吨锂金属分母复算。",
                    inferred=True,
                    note="CR3为澳大利亚、中国、智利；CR5再加津巴布韦、阿根廷。",
                    scope=metric,
                )
            )
        for company, share in (
            ("SQM", 14.0),
            ("Albemarle", 12.0),
            ("赣锋锂业", 6.0),
            ("天齐锂业", 5.0),
            ("Rio Tinto", 4.0),
        ):
            rows.append(
                _dp(
                    "sqm_20f_2025",
                    f"{company}全球锂化学品销售份额",
                    "2025",
                    "%",
                    share,
                    "SQM在20-F中估计的全球锂化学品销售份额。",
                    scope=f"global_lithium_chemical_share_{company}",
                )
            )
        rows.extend(
            [
                _dp(
                    "sqm_20f_2025",
                    "SQM锂产品销量",
                    "2025",
                    "万吨LCE",
                    25.79,
                    "SQM 2025年锂及衍生品销量为25.79万吨LCE。",
                    scope="global_lithium_operator_SQM_sales",
                ),
                _dp(
                    "albemarle_10k_2025",
                    "Albemarle权益锂金属产量",
                    "2025",
                    "千吨锂金属",
                    42.0,
                    (
                        "Albemarle按权益披露Greenbushes 19千吨、Wodgina 8千吨、"
                        "Salar de Atacama 14千吨、Silver Peak 1千吨锂金属。"
                    ),
                    scope="global_lithium_operator_Albemarle_attributable_output",
                ),
                _dp(
                    "rio_annual_2025",
                    "Rio Tinto权益锂产量",
                    "2025",
                    "千吨LCE",
                    57.0,
                    "Rio Tinto披露2025年权益口径锂产量57千吨LCE。",
                    scope="global_lithium_operator_Rio_output",
                ),
                _dp(
                    "pls_annual_2025",
                    "Pilgangoora锂精矿产量",
                    "FY2025",
                    "万吨",
                    75.46,
                    "PLS披露FY2025 Pilgangoora锂精矿产量75.46万吨。",
                    scope="global_lithium_project_Pilgangoora_output",
                ),
                _dp(
                    "pls_annual_2025",
                    "Pilgangoora单位运营成本",
                    "FY2025",
                    "澳元/干吨精矿",
                    627.0,
                    "PLS披露FY2025 FOB且不含运费和特许权使用费的单位运营成本。",
                    scope="global_lithium_project_Pilgangoora_cost",
                ),
                _dp(
                    "igo_annual_2025",
                    "Greenbushes锂精矿产量",
                    "FY2025",
                    "万吨",
                    147.9,
                    "IGO按Greenbushes项目100%口径披露FY2025精矿产量147.9万吨。",
                    scope="global_lithium_project_Greenbushes_output",
                ),
                _dp(
                    "igo_annual_2025",
                    "Greenbushes生产现金成本",
                    "FY2025",
                    "澳元/吨精矿",
                    325.0,
                    "IGO披露Greenbushes FY2025生产现金成本为325澳元/吨。",
                    scope="global_lithium_project_Greenbushes_cost",
                ),
                _dp(
                    "minres_annual_2025",
                    "Mt Marion权益SC6出货",
                    "FY2025",
                    "万吨",
                    20.3,
                    "Mineral Resources披露FY2025 Mt Marion权益SC6等价出货20.3万吨。",
                    scope="global_lithium_project_Mt_Marion_shipments",
                ),
                _dp(
                    "minres_annual_2025",
                    "Wodgina权益SC6出货",
                    "FY2025",
                    "万吨",
                    21.4,
                    "Mineral Resources披露FY2025 Wodgina权益SC6等价出货21.4万吨。",
                    scope="global_lithium_project_Wodgina_shipments",
                ),
                _dp(
                    "liontown_annual_2025",
                    "Kathleen Valley锂精矿产量",
                    "FY2025",
                    "万吨",
                    29.4,
                    "Liontown披露投产首11个月生产29.4万吨、平均品位5.2% Li2O。",
                    scope="global_lithium_project_Kathleen_Valley_output",
                ),
                _dp(
                    "liontown_annual_2025",
                    "Kathleen Valley锂精矿平均品位",
                    "FY2025",
                    "% Li2O",
                    5.2,
                    "Liontown披露FY2025所产精矿平均Li2O品位5.2%。",
                    scope="global_lithium_project_Kathleen_Valley_grade",
                ),
                _dp(
                    "core_annual_2025",
                    "Finniss重启研究年产SC6",
                    "2025重启研究",
                    "万吨/年",
                    20.5,
                    "Core Lithium重启研究给出的SC6等价名义年产量。",
                    forecast=True,
                    scope="global_lithium_project_Finniss_restart_capacity",
                ),
                _dp(
                    "core_annual_2025",
                    "Finniss重启研究FOB成本上限",
                    "2025重启研究",
                    "澳元/吨SC6",
                    785.0,
                    "Core Lithium重启研究给出的FOB单位成本区间上限为785澳元/吨。",
                    forecast=True,
                    scope="global_lithium_project_Finniss_restart_cost",
                ),
                _dp(
                    "canada_lithium_facts_2026",
                    "加拿大锂矿产量",
                    "2024",
                    "千吨锂金属",
                    5.983,
                    "加拿大自然资源部披露两座在产矿山合计生产5,983吨锂。",
                    scope="lithium_mine_country_Canada_official",
                ),
                _dp(
                    "us_doe_thacker_pass",
                    "Thacker Pass一期碳酸锂目标产能",
                    "规划",
                    "万吨/年",
                    4.0,
                    "美国能源部披露Thacker Pass满产后约4万吨/年电池级碳酸锂。",
                    forecast=True,
                    scope="global_lithium_project_Thacker_Pass_capacity",
                ),
                _dp(
                    "us_doe_thacker_pass",
                    "Thacker Pass美国能源部贷款",
                    "2024",
                    "亿美元",
                    22.6,
                    "美国能源部披露贷款总额约22.6亿美元，含资本化利息。",
                    scope="global_lithium_project_Thacker_Pass_financing",
                ),
            ]
        )
        for metric, value in (("全球锂化学品CR3", 32.0), ("全球锂化学品CR5", 41.0)):
            rows.append(
                _dp(
                    "sqm_20f_2025",
                    metric,
                    "2025",
                    "%",
                    value,
                    "按SQM披露的同年企业销售份额复算；不是矿山产量集中度。",
                    inferred=True,
                    note="同年同分母份额加总。",
                    scope=metric,
                )
            )
        global_projects = [
            (
                "rio_rincon_202603",
                "Rincon电池级碳酸锂目标产能",
                "规划",
                "万吨/年",
                6.0,
                False,
            ),
            (
                "rio_rincon_202603",
                "Rincon预计首产年份",
                "计划",
                "年",
                2028.0,
                False,
            ),
            (
                "rio_rincon_202603",
                "Rincon总投资",
                "规划",
                "亿美元",
                25.0,
                False,
            ),
            (
                "rio_q1_2026",
                "Fenix 1B与Sal de Vida计划首产年份",
                "2026Q1披露",
                "年",
                2026.0,
                True,
            ),
            (
                "albemarle_kemerton_202602",
                "Kemerton Train 1停产维护事件",
                "2026-02",
                "项",
                1.0,
                False,
            ),
            (
                "igo_greenbushes_2026q1",
                "Greenbushes锂精矿季度产量",
                "2026Q1",
                "万吨",
                35.1,
                False,
            ),
            (
                "igo_greenbushes_2026q1",
                "Greenbushes锂精矿季度平均售价",
                "2026Q1",
                "美元/吨",
                1668.0,
                False,
            ),
            (
                "igo_greenbushes_2026q1",
                "Greenbushes季度EBITDA率",
                "2026Q1",
                "%",
                75.0,
                False,
            ),
            (
                "pls_pilgangoora_2026",
                "Pilgangoora P2000潜在锂精矿产能",
                "可研",
                "万吨/年",
                200.0,
                False,
            ),
        ]
        for source, metric, period, unit, value, forecast in global_projects:
            rows.append(
                _dp(
                    source,
                    metric,
                    period,
                    unit,
                    value,
                    "全球主要锂项目公司一手披露。",
                    forecast=forecast,
                    scope=f"global_project_{metric}",
                )
            )
        policy = [
            ("argentina_mining_2025", "阿根廷在产锂矿数量", "2025", "座", 7.0),
            ("argentina_mining_2025", "阿根廷锂出口额", "2025", "亿美元", 9.05),
            ("argentina_rigi_rincon_2025", "Rincon获批RIGI初始产能", "规划", "万吨/年", 5.3),
            ("chile_national_lithium_strategy", "智利Atacama国有多数权益起始年", "2031", "年", 2031.0),
            ("mali_lithium_2026", "马里两矿精矿计划产量", "2026", "万吨", 59.0587),
            ("mali_lithium_2026", "Goulamina国家及本地权益", "2026", "%", 35.0),
            ("mali_goulamina_agreement_2024", "Goulamina国家及本地权益", "2024协议", "%", 35.0),
            ("nigeria_lithium_plant", "尼日利亚加工厂原矿处理能力", "2026", "吨/日", 6000.0),
            ("bolivia_dle_contracts_2025", "玻利维亚CBC两座DLE工厂规划产能", "规划", "万吨/年", 3.5),
            ("mexico_litiomx_2025", "墨西哥国家锂业控制链条事件", "2025", "项", 1.0),
            ("australia_cmpti_2026", "澳大利亚合格关键矿物加工成本税收抵免", "2027起", "%", 10.0),
        ]
    else:
        model = json.loads(CARBONATE_SD_PATH.read_text(encoding="utf-8"))
        for row in model["rows"]:
            for metric, key in (
                ("中国碳酸锂产量", "domestic_output_mt"),
                ("中国碳酸锂进口", "imports_mt"),
                ("中国碳酸锂出口", "exports_mt"),
                ("中国碳酸锂可用供给", "available_supply_mt"),
                ("中国碳酸锂需求", "demand_mt"),
                ("中国碳酸锂供需余额", "balance_mt"),
            ):
                rows.append(
                    _dp(
                        (
                            "lithium_association_2025"
                            if row["year"] == 2025 and key == "domestic_output_mt"
                            else "smm_carbonate_2026h1"
                        ),
                        metric,
                        str(row["year"]),
                        "百万吨碳酸锂",
                        row[key],
                        "国内产量、进出口与需求约束下的碳酸锂产品平衡。",
                        forecast=row["year"] >= 2026,
                        inferred=not (
                            row["year"] == 2025
                            and key == "domestic_output_mt"
                        ),
                        note=(
                            "2025产量为锂业分会实际值；其余2025进出口、需求和"
                            "2026—2028中值的来源与计算见模型证据约束和预测区间。"
                        ),
                        scope=f"china_carbonate_model_{metric}",
                    )
                )
        observed = model["observed_2026_h1"]
        for metric, unit, value, source in (
            ("SMM口径碳酸锂产量", "万吨", observed["smm_domestic_output_mt"] * 100, "smm_carbonate_2026h1"),
            ("Mysteel/隆众口径碳酸锂产量下限", "万吨", observed["domestic_output_range_mt"][0] * 100, "cnfin_carbonate_2026h1"),
            ("公开统计碳酸锂产量上限", "万吨", observed["domestic_output_range_mt"][1] * 100, "cnmn_carbonate_2026h1"),
            ("碳酸锂进口量", "万吨", observed["imports_mt"] * 100, "smm_customs_carbonate_2026h1"),
            ("碳酸锂出口量", "万吨", observed["exports_mt"] * 100, "smm_customs_carbonate_2026h1"),
            ("1月碳酸锂月度需求", "万吨", observed["demand_monthly_start_end_mt"][0] * 100, "smm_carbonate_2026h1"),
            ("6月碳酸锂月度需求", "万吨", observed["demand_monthly_start_end_mt"][1] * 100, "smm_carbonate_2026h1"),
        ):
            rows.append(
                _dp(
                    source,
                    metric,
                    "2026H1",
                    unit,
                    value,
                    "2026年上半年碳酸锂市场与海关高频统计。",
                    scope=f"china_carbonate_2026h1_{metric}",
                )
            )
        for route, value in observed["route_output_mt"].items():
            rows.append(
                _dp(
                    "cnfin_carbonate_2026h1",
                    f"{route}路线碳酸锂产量",
                    "2026H1",
                    "万吨",
                    value * 100,
                    "隆众口径的上半年碳酸锂分路线产量。",
                    scope=f"china_carbonate_2026h1_route_{route}",
                )
            )
        rows.extend(
            [
                _dp(
                    "lithium_association_2025h1",
                    "中国碳酸锂企业CR10",
                    "2025H1",
                    "%",
                    51.0,
                    "锂业分会披露上半年碳酸锂前十企业产量占全国51%。",
                    scope="china_carbonate_company_cr10",
                ),
                _dp(
                    "lithium_association_2025_competition",
                    "中国万吨级碳酸锂生产企业数量",
                    "2025",
                    "家",
                    29.0,
                    "锂业分会年度数据披露29家企业碳酸锂产量超过1万吨。",
                    scope="china_carbonate_10kt_company_count",
                ),
            ]
        )
        direct = [
            ("miit_lithium_2026q1", "碳酸锂进口量", "2026Q1", "万吨", 8.3),
            ("miit_lithium_2026q1", "碳酸锂进口同比", "2026Q1", "%", 64.6),
            ("miit_lithium_2026q1", "碳酸锂平均价格同比", "2026Q1", "%", 98.9),
            ("cnfin_carbonate_2026h1", "Mysteel口径碳酸锂产量", "2026H1", "万吨", 59.5),
            ("cnmn_carbonate_2026h1", "SMM口径碳酸锂产量", "2026H1", "万吨", 63.0),
            ("cnmn_carbonate_2026h1", "SMM样本碳酸锂库存", "2026-05", "万吨", 13.73),
            ("bolivia_ylb_2026", "玻利维亚国有碳酸锂产量目标", "2026", "万吨", 0.36),
        ]
        for source, metric, period, unit, value in direct:
            rows.append(
                _dp(
                    source,
                    metric,
                    period,
                    unit,
                    value,
                    "公开机构或政府披露的碳酸锂产量、进口、价格或库存数据。",
                    forecast="目标" in metric,
                    scope=f"carbonate_direct_{metric}",
                )
            )
        policy = [
            ("zimbabwe_export_202602", "津巴布韦锂精矿出口禁令生效年份", "2026", "年", 2026.0),
            ("chile_maricunga_202602", "Maricunga计划最早投产年份", "2030", "年", 2030.0),
            ("bolivia_ylb_2026", "玻利维亚国有碳酸锂目标产量", "2026", "吨", 3600.0),
        ]
    for source, metric, period, unit, value in policy:
        rows.append(
            _dp(
                source,
                metric,
                period,
                unit,
                value,
                "政府原始政策或生产目标；政策通过有效供给、成本和现金回收传导。",
                forecast=period not in {"2025"},
                scope=f"policy_{metric}",
            )
        )
    return rows


def _build_company_facts(industry: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    model_hash = model["content_sha256"]
    for company in model["companies"]:
        name = company["company"]
        ticker = company["ticker"]
        source_ref = f"ar_{ticker.replace('.', '_')}_2025"
        for metric, unit, period, value in COMPANY_DIRECT_FACTS.get(name, []):
            rows.append(
                _dp(
                    source_ref,
                    metric,
                    period,
                    unit,
                    value,
                    f"{name}年度报告披露的项目、产能、权益或产量事实。",
                    company=name,
                    forecast=period in {"规划", "2026目标", "计划"},
                    scope=f"{industry}_{name}_{metric}",
                )
            )
        for scenario_name in ("下行情景", "基准情景", "上行情景"):
            for item in company["scenarios"][scenario_name]:
                year = int(item["year"])
                inputs = [
                    (
                        f"{scenario_name}产品销量",
                        "万吨LCE",
                        item["product_volume_10kt_lce"],
                    ),
                    (
                        f"{scenario_name}资源自给比例",
                        "%",
                        item["resource_share_pct"],
                    ),
                    (
                        f"{scenario_name}资源单位成本",
                        "万元/吨",
                        item["resource_cost_10k_rmb_t_incl_vat"],
                    ),
                    (
                        f"{scenario_name}归母净利润",
                        "亿元人民币",
                        item["net_income_rmb_bn"] * 10.0,
                    ),
                    (
                        f"{scenario_name}股权自由现金流近似",
                        "亿元人民币",
                        item["fcfe_rmb_bn"] * 10.0,
                    ),
                    (
                        f"{scenario_name}ROE",
                        "%",
                        item["roe_pct"] if item["roe_pct"] is not None else 0.0,
                    ),
                ]
                for metric, unit, value in inputs:
                    rows.append(
                        _dp(
                            source_ref,
                            metric,
                            str(year),
                            unit,
                            value,
                            f"{name}独立公司模型在{scenario_name}下的{year}年输入或结果。",
                            company=name,
                            forecast=True,
                            inferred=True,
                            note=(
                                f"模型哈希={model_hash}；"
                                f"{company['formula']['resource_profit']}；"
                                f"{company['formula']['processing_profit']}。"
                            ),
                            scope=f"{industry}_{name}_{metric}",
                        )
                    )
        value_range = company["independent_equity_value_range"]
        valuation_points = []
        if value_range.get("low_rmb_bn") is not None:
            valuation_points.append(
                ("独立核心估值下限", value_range["low_rmb_bn"] * 10.0)
            )
        if value_range.get("high_rmb_bn") is not None:
            valuation_points.append(
                ("独立核心估值上限", value_range["high_rmb_bn"] * 10.0)
            )
        for metric, value in valuation_points:
            rows.append(
                _dp(
                    source_ref,
                    metric,
                    "2026-07-24",
                    "亿元人民币",
                    value,
                    f"{name}独立核心估值结果；参考与诊断方法不并入区间。",
                    company=name,
                    forecast=True,
                    inferred=True,
                    note=f"模型哈希={model_hash}；供应商当前市值未进入独立模型。",
                    scope=f"{industry}_{name}_{metric}",
                )
            )
    return rows


def build_data_points(industry: str) -> list[dict[str, Any]]:
    if industry not in {"锂", "碳酸锂"}:
        raise ValueError(industry)
    rows = _build_industry_facts(industry) + _build_company_facts(industry)
    if any(not row["metric"] or not row["source_excerpt"] for row in rows):
        raise ValueError("存在空指标或空摘录")
    return rows


KEY_ARGUMENTS = {
    "锂": [
        {
            "source_ref": "usgs_mcs_2026",
            "argument": "锂资源并非地质稀缺，短中期约束在有效产能、项目爬坡、加工和政策。",
            "support": "2025年全球产量增长31%，但需求仍增长20%，说明高价会刺激供给，项目兑现速度决定阶段平衡。",
            "counter": "若非洲、阿根廷和中国回收同步超预期，短缺情景会明显后移。",
            "sentiment": "中性",
            "dimension": "供需",
        },
        {
            "source_ref": "sqm_20f_2025",
            "argument": "锂化学品CR5约41%，但矿端、盐湖、锂盐和客户认证集中度不能混写。",
            "support": "SQM估计2025年SQM、Albemarle、赣锋、天齐和Rio Tinto销售份额合计41%。",
            "counter": "这是SQM估计的化学品销售口径，不是官方矿山产量CR5。",
            "sentiment": "中性",
            "dimension": "竞争格局",
        },
        {
            "source_ref": "australia_req_202606",
            "argument": "澳大利亚矿山复产和扩产是2026—2028全球锂供给的上沿约束，不能把名义产能直接当作当年可售精矿。",
            "support": "澳大利亚政府季度报告持续以矿山产量、出口量和价格分别建模，说明供给兑现与价格需要分开处理。",
            "counter": "若低价使检修、停产或扩建延期，政府预测的供给上沿也可能下修。",
            "sentiment": "中性",
            "dimension": "供给兑现",
        },
        {
            "source_ref": "dongfang_lithium_20260222",
            "argument": "本地研报的项目、成本和周期判断只能作为供给模型的情景对照，不能替代公司公告和政府项目资料。",
            "support": "报告系统梳理了矿山、盐湖与企业项目，为二轮项目核验提供候选清单。",
            "counter": "报告发布时间之后的延期、政策和价格变化必须用新资料更新。",
            "sentiment": "中性",
            "dimension": "项目核验",
        },
    ],
    "碳酸锂": [
        {
            "source_ref": "miit_lithium_2026q1",
            "argument": "中国碳酸锂在2026年从库存去化转向产品紧平衡，但年度小缺口不等于单边价格。",
            "support": "一季度进口8.3万吨、同比增长64.6%，上半年产量口径仍存在59.5万—63.0万吨差异。",
            "counter": "高库存、进口、氢氧化锂转产和新增盐湖供给可缓冲年度缺口。",
            "sentiment": "看涨",
            "dimension": "产品供需",
        },
        {
            "source_ref": "dongwu_carbonate_20260226",
            "argument": "公司盈利弹性必须拆成资源量、加工量、成本和其他业务，不能直接按收入乘锂价。",
            "support": "资源型、外购加工型和多金属公司的利润结构明显不同，本研究为13家公司分别建模。",
            "counter": "项目、长协和库存细节不完整时只能给区间，不能输出伪精确单点。",
            "sentiment": "中性",
            "dimension": "盈利与估值",
        },
        {
            "source_ref": "haizheng_futures_20260724",
            "argument": "年度紧平衡与短期价格可以不同步，库存、仓单和期现结构决定缺口转化为价格的速度。",
            "support": "最新期货研究显示现货强度与远期预期并存，适合用作交易结构观察，不替代年度供需事实。",
            "counter": "期货研究的交易判断不能作为项目产量、进口或终端需求的一手证据。",
            "sentiment": "中性",
            "dimension": "库存与价格",
        },
        {
            "source_ref": "dongbei_carbonate_20260519",
            "argument": "碳酸锂供需与成本曲线需要多模型对账，卖方预测只提供外部情景，不直接决定本研究基准。",
            "support": "报告给出供需、价格和成本路径，可与本研究国内产量、进口和需求模型逐项比较。",
            "counter": "不同报告对库存、回收和产品转换覆盖不同，不能机械平均。",
            "sentiment": "中性",
            "dimension": "外部对账",
        },
    ],
}
