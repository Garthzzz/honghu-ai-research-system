#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Audited data definitions for the PCB-special-equipment B-track research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RUN_TAG = "pcb_equipment_b_20260719"
INDUSTRY_NAME = "PCB专用设备"
AS_OF_DATE = "2026-07-19"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    title: str
    publisher: str
    publish_date: str
    source_type: str
    quality_tier: int
    primary: bool
    file_path: str | None = None
    url: str | None = None
    source_subtype: str = "research_report"
    value_layer: str = "深度框架"
    note: str = ""
    snapshot_path: str | None = None
    # Explicit metadata: never infer language from a URL or publisher name.
    language: str = "zh"
    fetch_method: str | None = None


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec("hans_h", "大族数控H股招股书", "大族数控", "2026-01-29", "招股书", 1, True,
               "papers/PCB设备/大族数控H股招股书.pdf", source_subtype="prospectus", value_layer="双层",
               note="市场数据为招股书内Prismark/灼识咨询口径；公司经营数据为发行人披露。"),
    SourceSpec("cfmee_h", "芯碁微装H股招股章程", "芯碁微装", "2026-06-17", "招股书", 1, True,
               "papers/PCB设备/芯碁微装H股招股书.pdf", source_subtype="prospectus", value_layer="双层",
               note="市场份额为发行人委聘灼识咨询口径；公司经营数据为发行人披露。"),
    SourceSpec("dongwei_a", "东威科技招股说明书（申报稿）", "东威科技", "未标明", "招股书", 1, True,
               "papers/PCB设备/东威科技招股书.pdf", source_subtype="prospectus", value_layer="公司专项",
               note="本地申报稿签署日期留空；PDF metadata创建日2020-06-24仅用于文件识别。报告期截至2019年，当前判断须显示严重时效提示。"),
    SourceSpec("hans_a", "大族数控A股招股说明书（上会稿）", "大族数控", "未标明", "招股书", 1, True,
               "papers/PCB设备/大族数控A股招股书.pdf", source_subtype="prospectus", value_layer="公司专项",
               note="本地上会稿签署日期留空；PDF metadata创建日2021-08-25仅用于文件识别。历史产品与分类经营数据不冒充当前参数。"),
    SourceSpec("cfmee_a", "芯碁微装A股招股说明书", "芯碁微装", "2021-03-29", "招股书", 1, True,
               "papers/PCB设备/芯碁微装A股招股书.pdf", source_subtype="prospectus", value_layer="公司专项",
               note="历史客户与型号价格证据，不能证明当前采购关系。"),
    SourceSpec("guangfa_202607", "PCB设备的半导体化——挑战物理极限的工艺革命", "广发证券", "2026-07-01", "卖方深度", 3, False,
               "papers/PCB设备/20260701-广发证券-机械设备行业AI珠峰系列十三：PCB设备的半导体化——挑战物理极限的工艺革命.pdf",
               value_layer="深度框架", note="红板采购和募投表为卖方转引；正文明确样本与二手来源边界。"),
    SourceSpec("dongwu_202602", "PCB设备行业2026年度策略", "东吴证券", "2026-02-10", "卖方深度", 3, False,
               "papers/PCB设备/20260210-东吴证券-PCB设备行业2026年度策略：站在业绩兑现的前夕，关注方案升级与新技术的增量空间.pdf",
               value_layer="深度框架", note="用于机构估算和工艺观点，不作为客户订单一手证据。"),
    SourceSpec("tushare", "Tushare A股估值与财务结构化快照", "Tushare", "2026-07-17", "三方数据", 2, False,
               url="https://tushare.pro/", source_subtype="financial_database", value_layer="最新数据",
               note="A股daily_basic、income、fina_indicator、cashflow和balance sheet；2026Q1为累计口径。",
               snapshot_path="cache/pcb_equipment_research/company_financial_snapshot.json", fetch_method="api_tushare"),
    SourceSpec("yfinance", "Yahoo Finance/yfinance跨市场估值与财务快照", "Yahoo Finance / yfinance", "2026-07-17", "三方数据", 3, False,
               url="https://finance.yahoo.com/", source_subtype="financial_database", value_layer="最新数据",
               note="海外与台日欧公司行情及报表；原币并以同次汇率换算人民币。",
               snapshot_path="cache/pcb_equipment_research/company_financial_snapshot.json", language="en", fetch_method="api_yfinance"),
    SourceSpec("kla_pcb", "PCB与IC载板检测、成像及制程控制产品概览", "KLA", "2024-01-15", "website_material", 1, True,
               url="https://www.kla.com/wp-content/uploads/PCB___ICS_product_overview_Eng.pdf", source_subtype="company_product",
               value_layer="公司专项", note="KLA官方PCB与载板产品概览；Orbotech作为集团产品品牌。", language="en"),
    SourceSpec("kla_ttm", "TTM Technologies采用KLA Neos 800的客户案例", "KLA", "2021-07-21", "website_material", 1, True,
               url="https://ir.kla.com/news-events/press-releases/detail/406/ttm-technologies-speeds-up-pcb-solder-mask-processing-with",
               source_subtype="customer_case", value_layer="公司专项", note="KLA官方具名客户案例；时间较早。", language="en"),
    SourceSpec("kla_2025_10k", "KLA Corporation FY2025 Form 10-K", "KLA / SEC", "2025-08-08", "公告", 1, True,
               url="https://www.sec.gov/Archives/edgar/data/319201/000031920125000024/klac-20250630.htm",
               source_subtype="annual_report", value_layer="公司专项",
               note="官方10-K用于PCB and Component Inspection分部收入；该分部含component inspection，不能等同纯PCB设备收入。", language="en"),
    SourceSpec("mks_esi", "ESI PCB laser processing systems", "MKS Instruments / ESI", "未标明", "website_material", 1, True,
               url="https://esi.d1.mks.com/", source_subtype="company_product", value_layer="公司专项",
               note="ESI是MKS品牌，不是独立上市主体。", language="en"),
    SourceSpec("mycronic_atg", "Mycronic收购atg Luther & Maelzer", "Mycronic", "2021-05-10", "公告", 1, True,
               url="https://www.mycronic.com/news-events/our-press-releases/mycronic-to-acquire-atg-luther--maelzer/",
               source_subtype="m_and_a", value_layer="公司专项", note="Mycronic从Cohu收购atg；当前财务并入Mycronic。", language="en"),
    SourceSpec("mycronic_atg_current", "atg Mycronic裸板测试业务历史与当前归属", "Mycronic", "未标明", "website_material", 1, True,
               url="https://www.mycronic.com/product-areas/bare-board-testing/about-bare-board-testing/history/",
               source_subtype="company_history", value_layer="公司专项",
               note="Mycronic当前官方页面确认atg自2021年6月并入集团，并于2026年3月更名为atg Mycronic；网页核验日为2026-07-19。", language="en"),
    SourceSpec("nidec_history", "Nidec Advance Technology公司历史", "Nidec", "未标明", "website_material", 1, True,
               url="https://www.nidec.com/en/nidec-advancetechnology/corporate/about/history/", source_subtype="company_history",
               value_layer="公司专项", note="2014年成为Nidec全资子公司，2023年由Nidec-Read更名。", language="en"),
    SourceSpec("amada_via", "AMADA收购Via Mechanics", "AMADA", "2025-04-17", "公告", 1, True,
               url="https://www.amada.co.jp/files/2025/04/E_NR_250417_01.pdf", source_subtype="m_and_a", value_layer="公司专项",
               note="Via Mechanics于2025年成为AMADA全资子公司。", language="en"),
    SourceSpec("ushio_via", "Ushio收购Via Mechanics曝光业务", "Ushio", "2018-01-31", "公告", 1, True,
               url="https://www.ushio.co.jp/en/news/1001/2018-2018/500281.html", source_subtype="m_and_a", value_layer="公司专项",
               note="Via在2018年已出售曝光业务，当前卡位以钻孔/成型为主。", language="en"),
    SourceSpec("camtek_sale", "Camtek完成出售PCB业务", "Camtek", "2017-10-02", "公告", 1, True,
               url="https://www.camtek.com/news-and-events/pcbsaleclosing/", source_subtype="m_and_a", value_layer="公司专项",
               note="Camtek当前是半导体检测公司，不纳入当前PCB设备估值组。", language="en"),
    SourceSpec("mitsubishi_drill", "PCB laser drilling systems", "Mitsubishi Electric", "未标明", "website_material", 1, True,
               url="https://www.mitsubishielectric.com/fa/products/mecha/laser/items/drilling/index.html", source_subtype="company_product",
               value_layer="公司专项", note="三菱电机官方PCB激光钻孔产品页。", language="en"),
    SourceSpec("via_solution", "Via Mechanics PCB drilling and routing solutions", "Via Mechanics", "未标明", "website_material", 1, True,
               url="https://en.viamechanics.com/solution/", source_subtype="company_product", value_layer="公司专项",
               note="当前机械/激光钻孔和成型参数；曝光业务历史边界另见Ushio公告。", language="en"),
    SourceSpec("jcu_products", "JCU products and corporate profile", "JCU", "未标明", "website_material", 1, True,
               url="https://www.jcu-i.com/english/products/", source_subtype="company_product", value_layer="公司专项",
               note="JCU同时销售表面处理化学品和部分设备，不是纯设备公司。", language="en"),
    SourceSpec("lpkf_scope", "25 years of ProtoLaser", "LPKF", "2025-09-24", "website_material", 1, True,
               url="https://www.lpkf.com/en/news-press/press-releases-teaser/25-years-protolaser-from-vision-to-precision-revolution-in-electronics-manufacturing",
               source_subtype="company_product", value_layer="公司专项", note="PCB业务主要位于原型制作与激光细分，不能直接等同量产高多层主设备。", language="en"),
    SourceSpec("hans_laser_group", "大族数控PCB机械钻孔设备业务及集团关系说明", "大族激光", "未标明", "website_material", 1, True,
               url="https://www.hanslaser.com/news-focus/159.html", source_subtype="company_profile", value_layer="公司专项",
               note="官方页面核验大族激光与大族数控集团边界；抓取核验日为2026-07-19。"),
    SourceSpec("dongwei_web", "PCB电镀与湿制程设备业务介绍", "东威科技", "未标明", "website_material", 1, True,
               url="https://www.ksdwgroup.com/", source_subtype="company_product", value_layer="公司专项",
               note="官方产品与业务页；抓取核验日为2026-07-19。"),
    SourceSpec("zhengye_pcb", "PCB制程检测与辅助设备方案", "正业科技", "未标明", "website_material", 1, True,
               url="https://www.zhengyee.com/Product/scheme.html", source_subtype="company_product", value_layer="公司专项",
               note="官方PCB检测解决方案页；抓取核验日为2026-07-19。"),
    SourceSpec("tianzhun_electronics", "电子行业LDI、激光钻孔与AOI/AVI产品", "天准科技", "未标明", "website_material", 1, True,
               url="https://www.tztek.com/electronics", source_subtype="company_product", value_layer="公司专项",
               note="官方电子行业产品页；激光微孔应用与18+机械通孔分开。"),
    SourceSpec("inno_laser_web", "激光器与精密微加工产品概览", "英诺激光", "未标明", "website_material", 1, True,
               url="https://www.inno-laser.com/", source_subtype="company_product", value_layer="公司专项",
               note="官方业务页；PCB整机订单仍以交易所投资者关系记录为准。"),
    SourceSpec("yanmade_web", "FPC与精密电子测试设备业务概览", "燕麦科技", "未标明", "website_material", 1, True,
               url="https://yanmade.com/", source_subtype="company_product", value_layer="公司专项",
               note="官方产品页；FPC测试与18+刚性板裸板电测不使用同一市场口径。"),
    SourceSpec("jutze_web", "机器视觉AOI与自动化应用", "矩子科技", "未标明", "website_material", 1, True,
               url="https://www.jutze.com.cn/category.php?name=hangye", source_subtype="company_product", value_layer="公司专项",
               note="官方行业页；SMT/半导体AOI与裸板PCB AOI按工序分开。"),
    SourceSpec("gage_web", "精密印刷与电子制造设备产品", "凯格精机", "未标明", "website_material", 1, True,
               url="https://www.gkg.cn/product_list/1.html", source_subtype="company_product", value_layer="公司专项",
               note="官方产品页；用于确认SMT装联工序边界，不纳入裸板核心设备份额。"),
    SourceSpec("ymz_web", "PCB与IC载板AOI/AVI检测产品", "宜美智", "未标明", "website_material", 1, True,
               url="https://www.szymzkj.com/", source_subtype="company_product", value_layer="公司专项",
               note="官方产品页；私营主体无连续公开财务与独立估值。"),
    SourceSpec("taliang_web", "PCB钻孔、成型与自动化设备概览", "大量科技", "未标明", "website_material", 1, True,
               url="https://www.tlhome.com.tw/", source_subtype="company_product", value_layer="公司专项",
               note="官方产品页；PCB与半导体设备收入仍需分部披露。"),
    SourceSpec("csun_web", "光热制程、曝光与自动化设备概览", "志圣工业", "未标明", "website_material", 1, True,
               url="https://www.csun.com.tw/zh-hans/", source_subtype="company_product", value_layer="公司专项",
               note="官方业务页；PCB、面板与半导体业务不混合。"),
    SourceSpec("screen_ledia", "Ledia直接成像设备产品概览", "SCREEN PE Solutions", "未标明", "website_material", 1, True,
               url="https://www.screen.co.jp/pe/en/products/ledia", source_subtype="company_product", value_layer="公司专项",
               note="官方产品页；多层板、HDI与载板型号按应用分开。", language="en"),
    SourceSpec("schmoll_web", "PCB机械钻孔、成型、激光与自动化设备", "Schmoll Maschinen", "未标明", "website_material", 1, True,
               url="https://www.schmoll-maschinen.de/", source_subtype="company_product", value_layer="公司专项",
               note="官方产品页；私营公司无连续公开财务。", language="en"),
    SourceSpec("cohu_atg_sale", "Cohu签署出售atg Luther & Maelzer业务协议", "Cohu", "2021-05-10", "公告", 1, True,
               url="https://ir.cohu.com/static-files/ef91060a-0041-4f5b-8e5e-5a8446d83e84", source_subtype="m_and_a", value_layer="公司专项",
               note="8-K确认2021-05-10签署出售协议并预计当年6月底交割；当前归属还需Mycronic后续披露交叉核验。", language="en"),
    SourceSpec("ttm_2024_10k", "TTM Technologies 2024 Form 10-K", "TTM Technologies", "2025-02-24", "公告", 1, True,
               url="https://investors.ttm.com/sec-filings/all-sec-filings/content/0000950170-25-024839/ttmi-20241230.htm",
               source_subtype="annual_report", value_layer="公司专项",
               note="官方年报用于核验集团收入、业务边界和工厂数；不提供设备BOM。", language="en"),
    SourceSpec("isu_business", "ISU Petasys超高多层PCB业务介绍", "ISU Petasys", "未标明", "website_material", 1, True,
               url="https://www.isu.co.kr/eng/business/it.jsp", source_subtype="company_profile", value_layer="公司专项",
               note="官方业务页确认18层以上超高多层PCB定位；抓取核验日2026-07-19。", language="en"),
    SourceSpec("isu_factory", "ISU Petasys新闻中附带的第五工厂投资与进度信息", "ISU Petasys", "2025-09-12", "公告", 1, True,
               url="https://www.isu.co.kr/kor/prcenter/news_view.jsp?sno=863", source_subtype="capacity_project", value_layer="公司专项",
               note="招聘荣誉新闻附带提及约3000亿韩元第五工厂和目标2027年完工；未披露产能、设备BOM或供应商，不据此外推设备需求。", language="ko"),
    SourceSpec("shennan_thailand", "深南电路泰国工厂进展公告", "深南电路", "2024-04-11", "公告", 1, True,
               url="https://www.scc.com.cn/yskjcmsresource/document/20240411/963022504593457152.PDF",
               source_subtype="capacity_project", value_layer="公司专项",
               note="客户官方项目公告，披露日2024-04-11、正文落款2024-04-10；用于投资金额与进度，不自行补设备型号。"),
    SourceSpec("gce_2024", "金像电子 2024 年年报", "金像电子", "2025-03-30", "公告", 1, True,
               url="https://www.gce.com.tw/file/st/2024AnnualReport.pdf", source_subtype="annual_report", value_layer="公司专项",
               note="官方年报用于泰国工厂试产、认证与量产节奏；不推断具体供应商。"),
)


# Prismark/CIC in Hans CNC H-share prospectus, USD million. 2030 is a clearly
# labelled one-year extrapolation from the source's 2025-2029 CAGR.
GLOBAL_MARKET_USD_M = {2024: 7085, 2025: 8176, 2026: 9120, 2027: 9973, 2028: 10729, 2029: 11388, 2030: 12367}

REGIONAL_MARKET_USD_M: dict[int, dict[str, int]] = {
    2025: {"中国大陆": 4747, "中国台湾": 790, "韩国": 738, "日本": 641, "美洲": 378, "东南亚": 708, "其他": 175},
    2026: {"中国大陆": 5264, "中国台湾": 881, "韩国": 815, "日本": 704, "美洲": 420, "东南亚": 846, "其他": 191},
    2027: {"中国大陆": 5723, "中国台湾": 963, "韩国": 882, "日本": 758, "美洲": 456, "东南亚": 986, "其他": 204},
    2028: {"中国大陆": 6121, "中国台湾": 1036, "韩国": 940, "日本": 804, "美洲": 489, "东南亚": 1125, "其他": 216},
    2029: {"中国大陆": 6495, "中国台湾": 1064, "韩国": 987, "日本": 840, "美洲": 516, "东南亚": 1262, "其他": 224},
    2030: {"中国大陆": 7028, "中国台湾": 1146, "韩国": 1062, "日本": 899, "美洲": 558, "东南亚": 1458, "其他": 239},
}

REGIONAL_CAGR_2025_2029 = {
    "中国大陆": 8.2, "中国台湾": 7.7, "韩国": 7.6, "日本": 7.0,
    "美洲": 8.1, "东南亚": 15.5, "其他": 6.5,
}

EQUIPMENT_MARKET_USD_M: dict[int, dict[str, int]] = {
    2025: {"钻孔": 1735, "曝光": 1222, "检测": 1226, "电镀": 590, "压合": 476, "成型": 700, "贴附": 209, "其他": 2017},
    2026: {"钻孔": 1994, "曝光": 1350, "检测": 1374, "电镀": 664, "压合": 531, "成型": 774, "贴附": 229, "其他": 2205},
    2027: {"钻孔": 2241, "曝光": 1480, "检测": 1502, "电镀": 728, "压合": 579, "成型": 838, "贴附": 246, "其他": 2359},
    2028: {"钻孔": 2472, "曝光": 1612, "检测": 1612, "电镀": 781, "压合": 619, "成型": 892, "贴附": 260, "其他": 2481},
    2029: {"钻孔": 2683, "曝光": 1743, "检测": 1704, "电镀": 826, "压合": 653, "成型": 979, "贴附": 272, "其他": 2528},
    2030: {"钻孔": 2992, "曝光": 1905, "检测": 1851, "电镀": 899, "压合": 707, "成型": 1064, "贴附": 290, "其他": 2675},
}

EQUIPMENT_CAGR_2025_2029 = {"钻孔": 11.5, "曝光": 9.3, "检测": 8.6, "电镀": 8.8, "压合": 8.2, "成型": 8.7, "贴附": 6.7, "其他": 5.8}


HANS_2025_10M_PRODUCTS = {
    "钻孔": {"revenue_yi": 30.956, "volume": 4499, "asp_wan": 68.8},
    "曝光": {"revenue_yi": 2.475, "volume": 103, "asp_wan": 240.3},
    "检测": {"revenue_yi": 3.836, "volume": 501, "asp_wan": 76.6},
    "成型": {"revenue_yi": 2.376, "volume": 521, "asp_wan": 45.6},
    "贴附": {"revenue_yi": 0.954, "volume": 208, "asp_wan": 45.9},
}

CFMEE_DI_PRODUCTS = {
    2023: {"volume": 280, "asp_wan": 210.65},
    2024: {"volume": 378, "asp_wan": 204.47},
    2025: {"volume": 475, "asp_wan": 227.35, "revenue_yi": 10.799},
}

DOWNSTREAM_PROJECTS = (
    {"company": "景旺电子", "project": "类载板项目", "investment_yi": 24.0, "capacity_wan_sqm": 60.0, "equipment_yuan_per_sqm": 2908},
    {"company": "胜宏科技", "project": "AI高端HDI项目", "investment_yi": 17.0, "capacity_wan_sqm": 15.0, "equipment_yuan_per_sqm": 8271},
    {"company": "方正科技", "project": "AI高密度互连项目", "investment_yi": 21.0, "capacity_wan_sqm": 21.0, "equipment_yuan_per_sqm": 7244},
    {"company": "崇达技术", "project": "高阶HDI/SLP项目", "investment_yi": 35.0, "capacity_wan_sqm": 150.0, "equipment_yuan_per_sqm": 1234},
    {"company": "鹏鼎控股", "project": "高阶HDI/SLP项目", "investment_yi": 42.0, "capacity_wan_sqm": 49.0, "equipment_yuan_per_sqm": 6895},
)

# Deliberately transparent research assumptions.  This is an illustrative
# configuration, not a disclosed real project bill of materials.  Rows without
# a numeric investment are deliberately excluded from the countable subtotal:
# public material does not provide a common quantity/price contract for them.
STANDARD_LINE = (
    {"category": "机械钻孔与背钻", "count": 300, "asp_wan": 78.0, "investment_yi": 2.34, "basis": "红板采购样本与2023年以来样本均价；数量为本研究示意设备篮子假设，无产能分母"},
    {"category": "激光钻孔（可选HDI模块）", "count": 20, "asp_wan": 318.0, "investment_yi": 0.636, "basis": "卖方样本均价；18+机械通孔线可不配置或少配"},
    {"category": "LDI/DI曝光", "count": 20, "asp_wan": 240.3, "investment_yi": 0.481, "basis": "大族2025年前十个月曝光设备大类均价"},
    {"category": "真空压合", "count": 4, "asp_wan": 490.2, "investment_yi": 0.196, "basis": "大族2024年压合设备大类均价，商业化样本仅2台"},
    {"category": "VCP/连续电镀", "count": 4, "asp_wan": 865.0, "investment_yi": 0.346, "basis": "2023年以来公开项目样本均价"},
    {"category": "电测/飞针/专用测试", "count": 80, "asp_wan": 76.6, "investment_yi": 0.613, "basis": "大族2025年前十个月检测设备大类均价"},
    {"category": "AOI/AVI/X-ray（分别待标定）", "count": None, "asp_wan": None, "investment_yi": None, "basis": "三种技术路线不可互换；公开资料没有同一产线内各自数量和同口径单价，不计入小计"},
    {"category": "数控成型", "count": 60, "asp_wan": 45.6, "investment_yi": 0.274, "basis": "大族2025年前十个月成型设备大类均价"},
    {"category": "其他湿制程、贴附、上下料与厂内自动化", "count": None, "asp_wan": None, "investment_yi": None, "basis": "没有真实项目完整BOM，不以残差补数，不计入小计"},
)


COMPANY_IDENTITIES: tuple[dict[str, Any], ...] = (
    {"name": "大族数控", "listed_key": "hans_cnc", "ticker": "301200.SZ", "market": "A股", "role": "综合设备龙头", "group": "独立上市；大族激光控股", "products": "机械/激光钻孔、LDI、检测、成型、贴附，压合处于导入期", "customers": "臻鼎、欣兴、胜宏、深南、东山等合作客户；具体型号多数未披露", "summary": "全工序覆盖和规模交付最强，2024年中国全设备份额10.1%；高端背钻和海外服务是进一步抬升份额的关键。"},
    {"name": "大族激光", "listed_key": "hans_laser", "ticker": "002008.SZ", "market": "A股", "role": "控股集团/激光平台", "group": "大族数控控股股东，集团与子公司财务不可相加", "products": "激光加工平台及相关PCB装备", "customers": "集团披露与子公司披露边界不同", "summary": "能提供激光器、运动控制与制造协同，但集团业务纯度低，不能用合并财务替代大族数控PCB设备表现。"},
    {"name": "东威科技", "listed_key": "dongwei", "ticker": "688700.SH", "market": "A股", "role": "VCP/湿制程", "group": "独立上市主体", "products": "刚性板脉冲VCP、柔性板片对片/卷对卷VCP及湿制程", "customers": "历史披露鹏鼎、健鼎、深南、沪电、东山等购买设备大类", "summary": "深孔电镀均匀性和整线经验是核心壁垒；历史客户强，但当前高多层收入占比与最新型号参数仍需年报补证。"},
    {"name": "芯碁微装", "listed_key": "cfmee", "ticker": "688630.SH", "market": "A股", "role": "PCB直接成像", "group": "A/H同一经济主体，不重复计算", "products": "MAS、NEX、RTR、FAST及自动线，覆盖线路/阻焊/卷对卷", "customers": "历史披露深南、胜宏、景旺等；2025客户仍多匿名", "summary": "2025年全球PCB直接成像份额18.8%，产能利用率已接近满载；优势在直写光刻平台和自动线，风险在估值、客户验收节奏及细分口径混用。"},
    {"name": "正业科技", "listed_key": "zhengye", "ticker": "300410.SZ", "market": "A股", "role": "检测/智能制造相邻", "group": "独立上市、多业务", "products": "PCB检测及智能制造相关设备", "customers": "具体高多层型号与当前客户公开证据不足", "summary": "具有检测与自动化积累，但业务重组和PCB设备纯度限制横向估值，必须以分部收入和订单验证复苏。"},
    {"name": "天准科技", "listed_key": "tianzhun", "ticker": "688003.SH", "market": "A股", "role": "机器视觉相邻", "group": "独立上市、多业务", "products": "机器视觉、精密测量与工业自动化", "customers": "高多层PCB专用设备客户关系目前没有直接证据", "summary": "算法与视觉平台可迁移至检测，但公开资料不足以证明其已成为高多层PCB核心设备供应商，应放在相邻能力组而非份额榜。"},
    {"name": "英诺激光", "listed_key": "inno_laser", "ticker": "301021.SZ", "market": "A股", "role": "激光器/激光装备相邻", "group": "独立上市、多业务", "products": "超快、紫外激光器及微加工方案", "customers": "PCB高多层具体量产客户和设备收入未单列", "summary": "上游光源和精密微加工是潜在卡位，但激光微孔主要对应HDI/载板；不能把激光能力直接等同18+机械通孔设备份额。"},
    {"name": "燕麦科技", "listed_key": "yanmade", "ticker": "688312.SH", "market": "A股", "role": "自动测试相邻", "group": "独立上市", "products": "FPC及精密电子测试设备", "customers": "客户与高多层刚性板映射证据不足", "summary": "测试自动化能力真实，但应用重心偏FPC，与高多层刚性裸板电测并非同一分母，估值只能作为相邻自动测试参照。"},
    {"name": "矩子科技", "listed_key": "juzitech", "ticker": "300802.SZ", "market": "A股", "role": "AOI/机器视觉相邻", "group": "独立上市、多业务", "products": "机器视觉检测与自动化", "customers": "高多层PCB专用收入和具名客户未单列", "summary": "视觉软件和检测集成具有迁移价值，但缺少同口径PCB专用分部数据，不能与KLA或裸板AOI供应商机械比较份额。"},
    {"name": "凯格精机", "listed_key": "gage", "ticker": "301338.SZ", "market": "A股", "role": "精密自动化相邻", "group": "独立上市、多业务", "products": "精密自动化、印刷和电子制造装备", "customers": "高多层板核心工序具体客户目前没有直接证据", "summary": "自动化能力可受益于PCB厂无人化，但不是钻孔、压合、电镀或检测核心工艺的直接纯标的。"},
    {"name": "宜美智", "ticker": None, "market": "其他", "role": "检测设备私营主体", "group": "未核验独立上市证券", "products": "裸板电测、视觉与AOI等", "customers": "红板采购样本显示检测设备应用；仍需交易所原文复核", "summary": "在客户采购样本中显示较强测试份额，但缺独立公开财务、共同分母市场份额和当前产能，适合业务对照而非估值对照。"},
    {"name": "大量科技", "listed_key": "ta_liang", "ticker": "3167.TW", "market": "其他", "role": "钻孔/成型", "group": "中国台湾上市主体", "products": "PCB钻孔、成型及自动化设备", "customers": "具体18+客户与型号需官方材料补证", "summary": "具备台湾供应链和设备经验，但 yfinance 报表期有限；需用公司年报分部数据确认高多层业务纯度。"},
    {"name": "志圣工业", "listed_key": "csun", "ticker": "2467.TW", "market": "其他", "role": "热制程/曝光/自动化", "group": "中国台湾上市主体", "products": "热制程、曝光及自动化相关设备", "customers": "具体高多层客户与型号未系统公开", "summary": "强项是热制程和区域客户基础，财务为集团口径；与纯钻孔或LDI公司的业务结构不具直接可比性。"},
    {"name": "三菱电机", "listed_key": "mitsubishi_electric", "ticker": "6503.T", "market": "其他", "role": "激光钻孔海外龙头", "group": "日本上市集团，PCB激光钻孔不单独披露财务", "products": "CO2/UV PCB激光钻孔系统", "customers": "红板样本显示三菱设备，但需区分代理商和制造商", "summary": "光源、振镜、F-theta光学和控制一体化形成高壁垒；集团业务庞大使估值不能解释PCB设备单一景气。"},
    {"name": "SCREEN Holdings", "listed_key": "screen", "ticker": "7735.T", "market": "其他", "role": "直接成像/湿制程", "group": "日本上市集团，PCB设备在PE Solutions", "products": "Ledia系列直接成像及PCB制程设备", "customers": "官方产品聚焦HDI/载板，18+刚性板专用收入未披露", "summary": "精密成像和海外服务成熟，但产品应用混合HDI与载板；应以分部数据而非集团半导体业务估值。"},
    {"name": "JCU", "listed_key": "jcu", "ticker": "4975.T", "market": "其他", "role": "化学品+湿制程设备", "group": "日本上市主体", "products": "表面处理化学品及自动化设备", "customers": "PCB设备与化学品客户边界未统一披露", "summary": "电镀工艺配方与设备协同是优势，但收入以化学品为主；不能把集团收入全部计入PCB设备市场。"},
    {"name": "Nidec Advance Technology（原Nidec-Read）", "listed_key": "nidec", "ticker": None, "market": "其他", "role": "电测/检测", "group": "2014年起Nidec全资子公司，2023年更名；无独立上市财务", "products": "PCB/封装基板电测、检测及自动化", "customers": "官方产品参数可核验，客户多不具名", "summary": "高密度电测与精密接触技术强，但只可引用Nidec集团财务作为母公司背景，不能贴成子公司独立营收。"},
    {"name": "Nidec", "listed_key": "nidec", "ticker": "6594.T", "market": "其他", "role": "母公司财务参照", "group": "Nidec Advance Technology母公司；集团财务不等于PCB检测子公司财务", "products": "综合电机与精密设备集团；PCB检测业务由Nidec Advance Technology承载", "customers": "子公司客户不得从集团财务反推", "summary": "仅用于展示上市母公司的市场与财务背景；不得把Nidec集团收入、利润或估值归为PCB检测业务。"},
    {"name": "Via Mechanics", "listed_key": "amada", "ticker": None, "market": "其他", "role": "机械/激光钻孔与成型", "group": "2025年成为AMADA全资子公司；2018年已出售曝光业务", "products": "机械钻孔、激光钻孔、成型", "customers": "具体当前客户未公开", "summary": "精密钻孔是核心卡位；当前身份和业务边界必须按AMADA并表、排除已出售曝光业务，避免沿用旧研报公司图谱。"},
    {"name": "AMADA", "listed_key": "amada", "ticker": "6113.T", "market": "其他", "role": "母公司财务参照", "group": "2025年收购Via Mechanics；集团财务不等于Via PCB设备财务", "products": "综合金属加工设备集团；Via作为电子制造设备业务单元", "customers": "Via客户和型号不得从AMADA集团财务反推", "summary": "只提供Via当前母公司的估值与财务背景；收购后的分部拆分和协同需要AMADA后续年报验证。"},
    {"name": "Schmoll", "ticker": None, "market": "其他", "role": "高精机械钻孔", "group": "德国私营主体", "products": "机械钻孔、背钻、激光与计量", "customers": "红板采购样本可证明供应商大类，具体型号未披露", "summary": "高端机械钻孔的稳定性和客户验证深，构成国产替代硬基准；私营且财务不公开，不能进入PE对比。"},
    {"name": "atg Mycronic（原atg L&M）", "listed_key": "mycronic", "ticker": None, "market": "其他", "role": "裸板电测", "group": "2021年由Mycronic从Cohu收购，当前并入Mycronic", "products": "飞针与裸板电测系统", "customers": "官方产品规格公开，客户和高多层收入未单列", "summary": "飞针测试的针距、重复性和高压能力是优势；品牌财务不能与Mycronic集团再相加。"},
    {"name": "LPKF", "listed_key": "lpkf", "ticker": "LPK.DE", "market": "其他", "role": "激光微加工/原型相邻", "group": "德国上市主体", "products": "ProtoLaser等PCB原型和激光加工", "customers": "高产量18+核心产线客户未直接披露", "summary": "适合原型、小批量和激光细分，不应仅因拥有PCB激光产品就列入高多层量产核心份额组。"},
    {"name": "KLA", "listed_key": "kla", "ticker": "KLAC", "market": "美股", "role": "AOI/LDI/制程控制", "group": "Orbotech业务并入KLA", "products": "Discovery、Ultra Dimension、Nuvogo、Neos等", "customers": "KLA披露TTM采用Neos 800阻焊方案", "summary": "算法、缺陷数据库、光学和全球服务形成高端检测/成像壁垒；集团半导体业务占比高，估值不可直接归因PCB。"},
    {"name": "MKS Instruments", "listed_key": "mks", "ticker": "MKSI", "market": "美股", "role": "激光微加工平台", "group": "ESI为MKS品牌/业务", "products": "ESI CapStone、Geode等PCB激光微加工系统", "customers": "公开规格多，具名高多层客户有限", "summary": "激光、光束控制和工艺数据库强，主要优势落在HDI/柔性/微孔；与18+机械钻孔的核心价值链应分开。"},
    {"name": "ESI", "listed_key": "mks", "ticker": None, "market": "其他", "role": "MKS激光设备品牌", "group": "非独立上市主体，财务并入MKS", "products": "PCB激光钻孔和微加工系统", "customers": "公开产品参数，独立财务和当前高多层客户未披露", "summary": "产品证据应归ESI品牌，估值和集团财务归MKS；两者不得作为两家公司重复进入份额或气泡图。"},
    {"name": "Cohu", "listed_key": "cohu", "ticker": "COHU", "market": "美股", "role": "历史卖方/当前排除", "group": "2021年将atg出售给Mycronic", "products": "当前核心为半导体测试与接口，不再拥有atg PCB业务", "customers": "不适用当前PCB设备客户核验", "summary": "只保留并购历史和估值排除说明；当前财务不应出现在PCB设备可比组。"},
    {"name": "Orbotech", "listed_key": "kla", "ticker": None, "market": "其他", "role": "KLA旗下PCB产品品牌", "group": "已被KLA收购，非独立上市主体", "products": "AOI、LDI和相关PCB制程控制产品", "customers": "产品/案例按KLA官方披露", "summary": "品牌仍具行业识别度，但财务、估值和市场主体归KLA；不能保留历史Orbotech独立市值。"},
    {"name": "Camtek", "listed_key": "camtek", "ticker": "CAMT", "market": "美股", "role": "历史PCB业务/当前排除", "group": "2017年完成出售PCB业务", "products": "当前聚焦半导体检测与量测", "customers": "当前PCB客户不适用", "summary": "现公司不是PCB设备可比标的；保留它是为了纠正旧研报名单，而不是把高估值半导体业务混入PCB设备。"},
    {"name": "Mycronic", "listed_key": "mycronic", "ticker": "MYCR.ST", "market": "其他", "role": "检测/组装/图形化集团", "group": "瑞典上市主体，2021年收购atg", "products": "atg裸板电测及集团其他生产解决方案", "customers": "atg产品规格公开，集团PCB分部拆分有限", "summary": "通过atg进入裸板测试，具全球销售服务协同；估值需注意集团其他业务，不能把Cohu历史或atg品牌再次加总。"},
)


# 只有具备明确发生日期、且描述真实公司行为的官方公告才进入“公司事件”。
# 产品页、公司介绍、招股书和财务快照继续作为画像证据，但不得包装成近期动向。
COMPANY_EVENT_SOURCE_KEYS: dict[str, str] = {
    "Via Mechanics": "amada_via",
    "AMADA": "amada_via",
    "atg Mycronic（原atg L&M）": "mycronic_atg",
    "Cohu": "cohu_atg_sale",
    "Camtek": "camtek_sale",
    "Mycronic": "mycronic_atg",
}


CORE_IDENTITY_NAMES = {item["name"] for item in COMPANY_IDENTITIES}
