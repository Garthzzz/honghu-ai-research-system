from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.opportunity_lens.run_pack_builder import RunPackBuilder
from tools.opportunity_lens.silicon_expansion_models import (
    build_model_outputs,
)
from tools.opportunity_lens.silicon_equipment_financial_supplement import (
    build_current_valuation_data_point,
    build_target_data_points as build_supplemental_financial_points,
    current_snapshot_spec,
    source_rows as supplemental_financial_source_rows,
    target_spec as supplemental_financial_target_spec,
)
from tools.opportunity_lens.silicon_run_pack_support import (
    SEGMENT_FACTOR_CODES,
    apply_data_point_evidence_audit,
    apply_financial_evidence_audit,
    apply_source_catalog_corrections,
    build_financial_data_points,
    build_segment_entity,
    extract_primary_research_question,
    natural_citations,
    normalize_agent_data_points,
    normalize_agent_source,
    sha256_file,
    source_uri,
    write_json,
    write_pack_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
AS_OF_DATE = "2026-07-19"
SLUG = "20260720_silicon_wafer_equipment_landscape_2026_2030"
DISPLAY_TITLE = "硅片制造设备格局与受益标的"
DEFAULT_OUTPUT_DIR = ROOT / "opportunity_lens" / "research_outputs" / SLUG
INTAKE_PATH = ROOT / "opportunity_lens" / "intake_requests" / "Opportunity_Lens_用户研究请求_硅片厂设备侧格局.md"
AGENT_DIR = ROOT / "cache" / "opportunity_lens" / "silicon_expansion_20260719" / "agents"
EQUIPMENT_DIR = AGENT_DIR / "equipment"
DEMAND_DIR = AGENT_DIR / "demand"
FINANCIAL_DIR = AGENT_DIR / "financials"
EQUIPMENT_AUDIT_PATH = AGENT_DIR / "equipment_evidence_audit" / "data_point_evidence_audit.json"
FINANCIAL_AUDIT_PATH = AGENT_DIR / "financial_evidence_audit" / "financial_evidence_audit.json"
FINANCIAL_TARGETS_PATH = FINANCIAL_DIR / "target_financials.json"
FINANCIAL_SOURCES_PATH = FINANCIAL_DIR / "normalized_sources.json"
FINANCIAL_SUPPLEMENT_MODULE_PATH = (
    ROOT / "tools" / "opportunity_lens" / "silicon_equipment_financial_supplement.py"
)


LEGAL_ENTITY_SOURCE: dict[str, Any] = {
    "source_id": "S064",
    "original_url_or_locator": "https://static.sse.com.cn/stock/disclosure/announcement/c/202508/002043_20250807_Q18T.pdf",
    "title": "西安奕斯伟材料科技股份有限公司首次公开发行股票并在科创板上市招股说明书（上会稿）",
    "title_zh": "西安奕材招股说明书（上会稿）：芯晖装备法人及业务边界",
    "publisher": "西安奕材/上海证券交易所",
    "date": "2025-08-07",
    "tier": "T1-监管披露",
    "language": "zh",
    "excerpt": (
        "招股书释义明确：‘芯晖装备’指浙江芯晖装备技术有限公司；‘奕斯伟设备’指西安芯晖设备技术有限公司，"
        "曾用名西安奕斯伟设备技术有限公司。第74页进一步列示，西安芯晖设备是12英寸硅片拉晶设备公司，"
        "浙江芯晖装备为另一独立法人。"
    ),
    "excerpt_zh": (
        "招股书释义明确：‘芯晖装备’指浙江芯晖装备技术有限公司；‘奕斯伟设备’指西安芯晖设备技术有限公司，"
        "曾用名西安奕斯伟设备技术有限公司。第74页进一步列示，西安芯晖设备是12英寸硅片拉晶设备公司，"
        "浙江芯晖装备为另一独立法人。"
    ),
    "local_locator": "PDF第12页释义第311—314行；PDF第74页第2375—2408行，两个法人及12英寸拉晶业务定位",
    "independence_key": "issuer:eswin:prospectus_2025_legal_entities",
    "independence_rationale": "发行人招股书对两个法人、曾用名和业务定位的直接监管披露。",
}


HISTORICAL_CYCLE_SOURCE: dict[str, Any] = {
    "source_id": "S065",
    "original_url_or_locator": (
        "https://www.semi.org/en/semi-press-release/"
        "worldwide-silicon-wafer-shipments-and-revenue-start-recovery-in-late-2024-semi-reports"
    ),
    "title": "Worldwide Silicon Wafer Shipments and Revenue Start Recovery in Late 2024, SEMI Reports",
    "title_zh": "SEMI：2024年下半年全球硅晶圆需求开始复苏",
    "publisher": "SEMI Silicon Manufacturers Group",
    "date": "2025-02-13",
    "tier": "T1-行业协会原始统计",
    "language": "en",
    "excerpt": (
        "Annual Silicon Industry Trends. Area Shipments (MSI), 2020/2021/2022/2023/2024: "
        "12,407/14,165/14,713/12,602/12,266. Revenues ($Billion): "
        "11.2/12.6/13.8/12.3/11.5. In the second half of 2024, worldwide silicon wafer "
        "demand started to recover from the industry downcycle seen in 2023."
    ),
    "excerpt_zh": (
        "SEMI年度硅产业趋势显示，2020—2024年全球硅晶圆出货面积依次为12,407、14,165、"
        "14,713、12,602和12,266百万平方英寸，销售额依次为112、126、138、123和115亿美元；"
        "2024年下半年，全球硅晶圆需求开始从2023年的行业下行周期中恢复。"
    ),
    "local_locator": (
        "网页正文‘Annual Silicon Industry Trends’表，检索2020—2024 Area Shipments和Revenues；"
        "正文检索‘started to recover from the industry downcycle seen in 2023’。"
    ),
    "independence_key": "association:semi:wafer_cycle_2020_2024",
    "independence_rationale": "SEMI硅制造商组发布的全球硅晶圆年度出货与销售额原始统计。",
}


# 同一监管文件包含多个相互独立的公开事实。公开抽屉按事实簇拆分引用，
# 但保留原文件的 independence_key，因此不会虚增独立证据组。
CRITICAL_FACT_CLUSTER_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "S066",
        "original_url_or_locator": "local_pdf_text/沪硅产业询问函.txt",
        "title": "沪硅产业审核问询回复：两条300毫米完整线的生产设备投入",
        "title_zh": "沪硅产业审核问询回复：两条300毫米完整线的生产设备投入",
        "publisher": "上海硅产业集团股份有限公司/上交所",
        "date": "2025",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "公司名称／新增产能／生产设备投资：标的公司，30万片/月，334,614.10万元；西安奕材第一工厂，50万片/月，678,768.03万元。",
        "excerpt_zh": "公司名称／新增产能／生产设备投资：标的公司，30万片/月，334,614.10万元；西安奕材第一工厂，50万片/月，678,768.03万元。",
        "local_locator": "PDF生产设备投资比较表；本地文本检索‘334,614.10’和‘678,768.03’，核对对应新增产能30万片/月和50万片/月。",
        "independence_key": "shanghai_silicon_regulatory_2025",
        "independence_rationale": "与同一发行人监管回复中的其他摘录合并计为一个证据组；这里只按事实主题拆分展示。",
    },
    {
        "source_id": "S067",
        "original_url_or_locator": "local_pdf_text/上海超硅招股书.txt",
        "title": "上海超硅招股书：300毫米硅片产能、产量、利用率与售价",
        "title_zh": "上海超硅招股书：300毫米硅片产能、产量、利用率与售价",
        "publisher": "上海超硅/上交所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "单位：万片。300mm半导体硅片：2023年产能133.57、产量111.16；2024年产能230.00、产量199.91；2025年产能367.00、产量275.93、产能利用率75.18%。300mm半导体硅片平均价格分别为385.97元/片、366.98元/片和322.57元/片。",
        "excerpt_zh": "单位：万片。300mm半导体硅片：2023年产能133.57、产量111.16；2024年产能230.00、产量199.91；2025年产能367.00、产量275.93、产能利用率75.18%。300mm半导体硅片平均价格分别为385.97元/片、366.98元/片和322.57元/片。",
        "local_locator": "招股书印刷页1-1-181及产销价格表；本地文本检索‘产能133.57’、‘产能367.00’、‘75.18%’和‘385.97元/片’。",
        "independence_key": "super_silicon_listing_2026",
        "independence_rationale": "与同一份招股书中的其他摘录合并计为一个证据组；这里只展示产销事实。",
    },
    {
        "source_id": "S068",
        "original_url_or_locator": "local_pdf_text/上海超硅招股书.txt",
        "title": "上海超硅招股书：300毫米薄层外延项目设备及安装预算",
        "title_zh": "上海超硅招股书：300毫米薄层外延项目设备及安装预算",
        "publisher": "上海超硅/上交所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "本项目达产后将新增年产180万片300毫米薄层硅外延片产能，建设期24个月，投资总额298,081.96万元；设备购置及安装费278,565.75万元，占投资比例93.46%。",
        "excerpt_zh": "本项目达产后将新增年产180万片300毫米薄层硅外延片产能，建设期24个月，投资总额298,081.96万元；设备购置及安装费278,565.75万元，占投资比例93.46%。",
        "local_locator": "招股书印刷页1-1-332；本地文本检索‘设备购置及安装费278,565.75万元’和‘93.46%’。",
        "independence_key": "super_silicon_listing_2026",
        "independence_rationale": "与同一份招股书中的其他摘录合并计为一个证据组；这里只展示外延项目预算。",
    },
    {
        "source_id": "S069",
        "original_url_or_locator": "local_pdf_text/上海超硅招股书.txt",
        "title": "上海超硅招股书：应用材料常压外延系统合同",
        "title_zh": "上海超硅招股书：应用材料常压外延系统合同",
        "publisher": "上海超硅/上交所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "APPLIED MATERIALS SOUTH EAST ASIA PTE. LTD.，2022.08.29，常压外延系统，12,850.00万美元，正在履行；2021.11.08，常压外延系统，4,530.00万美元，履行完毕。",
        "excerpt_zh": "APPLIED MATERIALS SOUTH EAST ASIA PTE. LTD.，2022.08.29，常压外延系统，12,850.00万美元，正在履行；2021.11.08，常压外延系统，4,530.00万美元，履行完毕。",
        "local_locator": "招股书印刷页1-1-376至377；本地文本检索‘APPLIED MATERIALS’、‘12,850.00’和‘4,530.00’。",
        "independence_key": "super_silicon_listing_2026",
        "independence_rationale": "与同一份招股书中的其他摘录合并计为一个证据组；这里只展示应用材料合同。",
    },
    {
        "source_id": "S070",
        "original_url_or_locator": "local_pdf_text/上海超硅招股书.txt",
        "title": "上海超硅招股书：KLA缺陷检测与几何量测合同",
        "title_zh": "上海超硅招股书：KLA缺陷检测与几何量测合同",
        "publisher": "上海超硅/上交所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "KLA Corporation，2023.03.01，晶圆缺陷与表面质量检测仪，9,377.00万美元，正在履行；2023.03.15，同类设备3,300.00万美元，履行完毕；2022.06.20，晶圆几何形貌测量仪6,330.00万美元，正在履行。",
        "excerpt_zh": "KLA Corporation，2023.03.01，晶圆缺陷与表面质量检测仪，9,377.00万美元，正在履行；2023.03.15，同类设备3,300.00万美元，履行完毕；2022.06.20，晶圆几何形貌测量仪6,330.00万美元，正在履行。",
        "local_locator": "招股书印刷页1-1-376至377；本地文本检索‘KLA Corporation’、‘9,377.00’、‘3,300.00’和‘6,330.00’。",
        "independence_key": "super_silicon_listing_2026",
        "independence_rationale": "与同一份招股书中的其他摘录合并计为一个证据组；这里只展示KLA合同。",
    },
    {
        "source_id": "S071",
        "original_url_or_locator": "local_pdf_text/上海超硅招股书.txt",
        "title": "上海超硅招股书：研磨与双面抛光设备采购",
        "title_zh": "上海超硅招股书：研磨与双面抛光设备采购",
        "publisher": "上海超硅/上交所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "研磨机平均采购单价：2022年关联中间商453.81万元/台，2023年关联中间商556.29万元/台，2023年直接向招股书匿名研磨设备供应商采购505.57万元/台，2024年直接采购573.02万元/台。双面抛光机平均采购单价：2022年关联中间商937.27万元/台；2023年直接向SpeedFam/Lapmaster Wolters采购886.09万元/台。",
        "excerpt_zh": "研磨机平均采购单价：2022年关联中间商453.81万元/台，2023年关联中间商556.29万元/台，2023年直接向招股书匿名研磨设备供应商采购505.57万元/台，2024年直接采购573.02万元/台。双面抛光机平均采购单价：2022年关联中间商937.27万元/台；2023年直接向SpeedFam/Lapmaster Wolters采购886.09万元/台。",
        "local_locator": "招股书研磨机与双面抛光机采购单价表；本地文本检索‘453.81万元/台’、‘573.02万元/台’和‘886.09万元/台’。",
        "independence_key": "super_silicon_listing_2026",
        "independence_rationale": "与同一份招股书中的其他摘录合并计为一个证据组；这里只展示研磨抛光采购。",
    },
    {
        "source_id": "S072",
        "original_url_or_locator": "local_pdf_text/2026-04-28-605358.SH-立昂微-605358立昂微2025年年度报告.txt",
        "title": "立昂微2025年报：年产480万片300毫米大硅片项目投入进度",
        "title_zh": "立昂微2025年报：年产480万片300毫米大硅片项目投入进度",
        "publisher": "立昂微/上交所",
        "date": "2026-04-28",
        "tier": "T1-定期报告",
        "language": "zh",
        "excerpt": "年产480万片300mm大硅片生产基地建设项目：该项目预算总投资601,905.00万元，截至报告期末已完成项目投资294,763.26万元，项目进度48.97%。",
        "excerpt_zh": "年产480万片300mm大硅片生产基地建设项目：该项目预算总投资601,905.00万元，截至报告期末已完成项目投资294,763.26万元，项目进度48.97%。",
        "local_locator": "年报非募集资金投资项目表；本地文本第1621—1622行，检索‘601,905.00万元’、‘294,763.26万元’和‘48.97%’。",
        "independence_key": "leon_annual_2025",
        "independence_rationale": "与同一份法定年报中的其他摘录合并计为一个证据组；这里只展示300毫米完整线项目。",
    },
    {
        "source_id": "S073",
        "original_url_or_locator": "local_pdf_text/2026-04-28-605358.SH-立昂微-605358立昂微2025年年度报告.txt",
        "title": "立昂微2025年报：年产180万片12英寸外延片项目进度与延期",
        "title_zh": "立昂微2025年报：年产180万片12英寸外延片项目进度与延期",
        "publisher": "立昂微/上交所",
        "date": "2026-04-28",
        "tier": "T1-定期报告",
        "language": "zh",
        "excerpt": "年产180万片12英寸半导体硅外延片项目，预算投资23.02亿元，工程进度20.60%；公司因已投产12英寸半导体硅外延片产能利用不足而放缓外延车间建设，对设备采购节奏进行阶段性调整，并将项目达到预定可使用状态日期延期至2027年12月。",
        "excerpt_zh": "年产180万片12英寸半导体硅外延片项目，预算投资23.02亿元，工程进度20.60%；公司因已投产12英寸半导体硅外延片产能利用不足而放缓外延车间建设，对设备采购节奏进行阶段性调整，并将项目达到预定可使用状态日期延期至2027年12月。",
        "local_locator": "年报在建工程及募投项目表与延期说明；本地文本检索‘23.02’、‘20.60%’、‘设备采购节奏’和‘2027年12月’。",
        "independence_key": "leon_annual_2025",
        "independence_rationale": "与同一份法定年报中的其他摘录合并计为一个证据组；这里只展示12英寸外延项目。",
    },
    {
        "source_id": "S074",
        "original_url_or_locator": "local_pdf_text/2026-04-28-605358.SH-立昂微-605358立昂微2025年年度报告.txt",
        "title": "立昂微2025年报：重掺衬底与轻掺外延项目投资",
        "title_zh": "立昂微2025年报：重掺衬底与轻掺外延项目投资",
        "publisher": "立昂微/上交所",
        "date": "2026-04-28",
        "tier": "T1-定期报告",
        "language": "zh",
        "excerpt": "投资22.62亿元的年产180万片12英寸重掺衬底硅片项目与投资23.02亿元的年产180万片12英寸半导体硅外延片项目形成全链条配套，投资12.30亿元的年产96万片12英寸轻掺硅外延片项目有序推进中。",
        "excerpt_zh": "投资22.62亿元的年产180万片12英寸重掺衬底硅片项目与投资23.02亿元的年产180万片12英寸半导体硅外延片项目形成全链条配套，投资12.30亿元的年产96万片12英寸轻掺硅外延片项目有序推进中。",
        "local_locator": "年报半导体硅片业务说明；本地文本第1029—1034行，检索‘22.62亿元’、‘23.02亿元’和‘12.30亿元’。",
        "independence_key": "leon_annual_2025",
        "independence_rationale": "与同一份法定年报中的其他摘录合并计为一个证据组；这里只展示重掺衬底和轻掺外延项目。",
    },
    {
        "source_id": "S075",
        "original_url_or_locator": "local_pdf_text/西安奕材 问询函.txt",
        "title": "西安奕材问询回复：国产CMP设备转固、付款与最终验收",
        "title_zh": "西安奕材问询回复：国产CMP设备转固、付款与最终验收",
        "publisher": "西安奕材/上交所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "发行人向芯晖装备采购的5台化学机械抛光设备，均已完成转固。截至本问询回复出具日，全部5台化学机械抛光设备价款，发行人已支付合同总价的79%；其中2台设备尚未完成合同验收，暂未支付验收款。",
        "excerpt_zh": "发行人向芯晖装备采购的5台化学机械抛光设备，均已完成转固。截至本问询回复出具日，全部5台化学机械抛光设备价款，发行人已支付合同总价的79%；其中2台设备尚未完成合同验收，暂未支付验收款。",
        "local_locator": "问询回复印刷页8-1-161及付款明细表；本地文本第6548—6553行和第6588—6594行，检索‘5台化学机械抛光设备’、‘79%’和‘2台设备尚未完成合同验收’。",
        "independence_key": "eswin_listing_2026",
        "independence_rationale": "与同一发行人上市问询回复中的其他摘录合并计为一个证据组；这里只展示CMP验收。",
    },
    {
        "source_id": "S076",
        "original_url_or_locator": "local_pdf_text/西安奕材 问询函.txt",
        "title": "西安奕材问询回复：国产研磨减薄设备尚未验收",
        "title_zh": "西安奕材问询回复：国产研磨减薄设备尚未验收",
        "publisher": "西安奕材/上交所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "发行人向芯晖装备采购3台研磨减薄设备，设备已能满足测试片生产需求，但生产后光滑度参数稳定性仍有不足，尚未通过验收，暂未转固；截至本问询回复出具日，全部3台设备价款已支付比例为90%。",
        "excerpt_zh": "发行人向芯晖装备采购3台研磨减薄设备，设备已能满足测试片生产需求，但生产后光滑度参数稳定性仍有不足，尚未通过验收，暂未转固；截至本问询回复出具日，全部3台设备价款已支付比例为90%。",
        "local_locator": "问询回复印刷页8-1-161；本地文本第6555—6559行，检索‘3台研磨减薄设备’、‘尚未通过验收’和‘90%’。",
        "independence_key": "eswin_listing_2026",
        "independence_rationale": "与同一发行人上市问询回复中的其他摘录合并计为一个证据组；这里只展示研磨减薄验收。",
    },
    {
        "source_id": "S077",
        "original_url_or_locator": "local_pdf_text/西安奕材 问询函.txt",
        "title": "西安奕材问询回复：芯晖装备在手合同与意向订单",
        "title_zh": "西安奕材问询回复：芯晖装备在手合同与意向订单",
        "publisher": "西安奕材/上交所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "截至2022年6月30日，奕斯伟设备来自发行人的拉晶设备在手合同约1.87亿元、意向订单约1.94亿元；芯晖装备在手合同合计1.15亿元、意向订单合计4.49亿元。截至2025年6月末，芯晖装备合并口径在手合同和意向订单金额超过5亿元，母公司（不含奕斯伟设备）单体约3亿元。",
        "excerpt_zh": "截至2022年6月30日，奕斯伟设备来自发行人的拉晶设备在手合同约1.87亿元、意向订单约1.94亿元；芯晖装备在手合同合计1.15亿元、意向订单合计4.49亿元。截至2025年6月末，芯晖装备合并口径在手合同和意向订单金额超过5亿元，母公司（不含奕斯伟设备）单体约3亿元。",
        "local_locator": "问询回复在手订单说明；本地文本第5913—5918、6018—6020及6145—6147行，分别检索‘1.87亿元’、‘1.94亿元’、‘1.15亿元’、‘4.49亿元’和‘超过5亿元’。",
        "independence_key": "eswin_listing_2026",
        "independence_rationale": "与同一发行人上市问询回复中的其他摘录合并计为一个证据组；这里只展示合同及意向订单。",
    },
    {
        "source_id": "S078",
        "original_url_or_locator": "local_pdf_text/沪硅产业询问函.txt",
        "title": "沪硅产业审核问询回复：300毫米二期项目总投资与2024年末产能",
        "title_zh": "沪硅产业审核问询回复：300毫米二期项目总投资与2024年末产能",
        "publisher": "上海硅产业集团股份有限公司/上交所",
        "date": "2025",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "上市公司300mm硅片二期项目总投资为67.10亿元，除了产线建设投资外，还包括委托上海新昇代为建设厂房的投资及营运资金等。截至2024年末，标的公司300mm半导体硅片产能已达到30万片/月。",
        "excerpt_zh": "上市公司300mm硅片二期项目总投资为67.10亿元，除了产线建设投资外，还包括委托上海新昇代为建设厂房的投资及营运资金等。截至2024年末，标的公司300mm半导体硅片产能已达到30万片/月。",
        "local_locator": "审核问询回复印刷页6-3-79；本地文本第3162—3174行，检索‘总投资为67.10亿元’和‘2024年末达到30万片/月’。",
        "independence_key": "shanghai_silicon_regulatory_2025",
        "independence_rationale": "与同一发行人监管回复中的其他摘录合并计为一个证据组；这里只展示项目总投资与已形成产能。",
    },
    {
        "source_id": "S079",
        "original_url_or_locator": "https://static.sse.com.cn/stock/disclosure/announcement/c/202211/001139_20221109_OMIZ.pdf",
        "title": "晶升股份审核问询回复：12英寸单晶炉客户、验收与量产应用",
        "title_zh": "晶升股份审核问询回复：12英寸单晶炉客户、验收与量产应用",
        "publisher": "晶升股份/上海证券交易所",
        "date": "2022-11-09",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": (
            "公司2015年与上海新昇签署业务合同并供应12英寸半导体级单晶硅炉设备，2018年度经上海新昇验收通过；"
            "后续开拓立昂微（金瑞泓）等客户，并向上述大尺寸硅片厂商批量供应12英寸半导体级单晶硅炉。"
            "公司为上海新昇、立昂微（金瑞泓）12英寸半导体级单晶硅炉的主要国内供应商，"
            "晶盛机电为TCL中环半导体级单晶硅炉的主要国内供应商。"
            "应用表显示，晶升装备用于上海新昇和金瑞泓的12英寸硅片均已实现量产。"
        ),
        "excerpt_zh": (
            "公司2015年与上海新昇签署业务合同并供应12英寸半导体级单晶硅炉设备，2018年度经上海新昇验收通过；"
            "后续开拓立昂微（金瑞泓）等客户，并向上述大尺寸硅片厂商批量供应12英寸半导体级单晶硅炉。"
            "公司为上海新昇、立昂微（金瑞泓）12英寸半导体级单晶硅炉的主要国内供应商，"
            "晶盛机电为TCL中环半导体级单晶硅炉的主要国内供应商。"
            "应用表显示，晶升装备用于上海新昇和金瑞泓的12英寸硅片均已实现量产。"
        ),
        "local_locator": (
            "PDF第6页第104—112行：2015年上海新昇合同、2018年验收及后续立昂微批量供货；"
            "第44页第1434—1451行：晶升股份主要供应上海新昇和立昂微，晶盛机电主要供应TCL中环；"
            "第46页第1495—1504行：上海新昇、金瑞泓12英寸应用及量产状态。"
        ),
        "independence_key": "cge_listing_2022",
        "independence_rationale": "与S030来自同一份晶升股份监管文件，合并计为一个证据组；这里只承载客户、验收和量产事实。",
    },
    {
        "source_id": "S080",
        "original_url_or_locator": "local_pdf_text/上海超硅招股书.txt",
        "title": "上海超硅招股书：匿名供应商B1研磨机合同",
        "title_zh": "上海超硅招股书：匿名供应商B1研磨机合同",
        "publisher": "上海超硅/上海证券交易所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "供应商B1，2022.04.27，研磨机，2,937.60万美元，正在履行。",
        "excerpt_zh": "招股书匿名供应商B1于2022年4月27日签署研磨机合同，金额2,937.60万美元（即29.376百万美元），合同正在履行。",
        "local_locator": (
            "原文标签‘供应商 B1’（公开表称‘招股书匿名研磨设备供应商’）；"
            "招股书印刷页1-1-376至377，本地文本第16579—16590行，"
            "检索‘供应商 B1’、‘2022.04.27’和‘2,937.60万美元’。"
        ),
        "independence_key": "super_silicon_listing_2026",
        "independence_rationale": "与同一份上海超硅招股书中的其他摘录合并计为一个证据组；这里只承载匿名研磨机合同。",
    },
    {
        "source_id": "S081",
        "original_url_or_locator": "local_pdf_text/上海超硅招股书.txt",
        "title": "上海超硅招股书：与Okamoto等终端设备生产商直接合作",
        "title_zh": "上海超硅招股书：与Okamoto等终端设备生产商直接合作",
        "publisher": "上海超硅/上海证券交易所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": (
            "设备方面，公司已逐步与日本Mabuchi、日本Yoshinaga Shoji等其他无关联第三方中间商社，"
            "以及日本Okamoto、供应商B等终端生产商（或其下属子公司）直接合作。"
        ),
        "excerpt_zh": (
            "设备方面，公司已逐步与日本Mabuchi、日本Yoshinaga Shoji等其他无关联第三方中间商社，"
            "以及日本Okamoto、供应商B等终端生产商（或其下属子公司）直接合作。"
        ),
        "local_locator": "招股书印刷页1-1-359附近；本地文本第15798—15801行，检索‘日本Okamoto’和‘终端生产商’。",
        "independence_key": "super_silicon_listing_2026",
        "independence_rationale": "与同一份上海超硅招股书中的其他摘录合并计为一个证据组；这里只证明采购渠道或合作关系，不证明具体机型或本轮项目合同。",
    },
    {
        "source_id": "S082",
        "original_url_or_locator": "local_pdf_text/上海超硅招股书.txt",
        "title": "上海超硅招股书：2025年末机器设备原值与账面价值",
        "title_zh": "上海超硅招股书：2025年末机器设备原值与账面价值",
        "publisher": "上海超硅/上海证券交易所",
        "date": "2026",
        "tier": "T1-监管披露",
        "language": "zh",
        "excerpt": "单位：万元。机器设备：原值710,733.24，累计折旧141,869.86，减值准备1,266.84，账面价值567,596.55。",
        "excerpt_zh": "单位：万元。机器设备：原值710,733.24，累计折旧141,869.86，减值准备1,266.84，账面价值567,596.55。",
        "local_locator": "招股书主要固定资产表及报告期固定资产构成表；本地文本第8014—8023行和第13416—13427行，检索‘机器设备710,733.24’。",
        "independence_key": "super_silicon_listing_2026",
        "independence_rationale": "与同一份上海超硅招股书中的其他摘录合并计为一个证据组；这里只承载机器设备原值及账面价值。",
    },
    {
        "source_id": "FIN-PVA-06",
        "original_url_or_locator": "https://www.pvatepla.com/fileadmin/sitepackage/pdf/investor_relations/hauptversammlung/2026/EN/4-PVA_TePla_Annual_Report_2025.pdf",
        "title": "PVA TePla Annual Report 2025: Semiconductor Systems segment results",
        "title_zh": "PVA TePla 2025年报：半导体系统分部收入与毛利率",
        "publisher": "PVA TePla AG",
        "date": "2026",
        "tier": "T1-发行人年报",
        "language": "en",
        "excerpt": (
            "Key figures by segment, in EUR '000: Semiconductor Systems revenue 187,578 in 2024 and 156,624 in 2025; "
            "gross profit 70,533 and 60,005. The gross margin remained stable at 37.7% (previous year: 37.3%). "
            "The reported gross profit and gross margin are calculated based on the respective segment's total revenue, "
            "including internal segment revenue."
        ),
        "excerpt_zh": (
            "单位为千欧元：半导体系统分部2024年和2025年收入分别为187,578和156,624，毛利润分别为70,533和60,005；"
            "2025年分部毛利率为37.7%，上年为37.3%。年报说明分部毛利率按包含内部收入的分部总收入计算。"
        ),
        "local_locator": "Annual Report 2025 PDF P105, lines 3132-3138 and 3153-3161。",
        "independence_key": "issuer:pva_tepla:annual_report_2025",
        "independence_rationale": "与FIN-PVA-01来自同一份PVA TePla 2025年报，合并计为一个证据组；这里只承载分部收入、毛利润和毛利率。",
    },
)

CRITICAL_FACT_CLUSTER_REFS = {
    str(source["source_id"]) for source in CRITICAL_FACT_CLUSTER_SOURCES
}


LOCAL_PATH_MAP = {
    "local_pdf_text/沪硅产业询问函.txt": "papers/硅片/沪硅产业询问函.pdf",
    "local_pdf_text/西安奕材 招股书.txt": "papers/硅片/西安奕材 招股书.pdf",
    "local_pdf_text/西安奕材 问询函.txt": "papers/硅片/西安奕材 问询函.pdf",
    "local_pdf_text/上海超硅招股书.txt": "papers/硅片/上海超硅招股书.pdf",
    "local_pdf_text/2026-04-28-605358.SH-立昂微-605358立昂微2025年年度报告.txt": "papers/硅片/2026-04-28-605358.SH-立昂微-605358立昂微2025年年度报告.pdf",
    "local_pdf_text/TCL中环2025年报.txt": "papers/硅片/TCL中环2025年报.pdf",
}


# 需求侧研究已经完成对下游晶圆厂扩产的一手来源核验。设备侧只复用其中
# 与“应用需求 -> 硅片品类 -> 制造工序”直接相关的九条来源，并在本包内重新编号，
# 避免两个独立 run 的 S 编号发生碰撞。原始来源仍由各自发布方负责，不能把
# 晶圆厂资本开支直接换算为硅片设备订单。
DEMAND_DRIVER_SOURCE_REF_MAP: dict[str, str] = {
    "S013": "S055",  # TSMC / AI 与先进逻辑
    "S020": "S056",  # Micron / DRAM
    "S025": "S057",  # SK hynix / HBM（历史规划）
    "S026": "S058",  # SK hynix / M15X 当前爬坡
    "S040": "S059",  # Kioxia / NAND 依靠既有洁净室
    "S045": "S060",  # 长江存储三期
    "S046": "S061",  # 长鑫在建资产
    "S035": "S062",  # Infineon / 300mm 功率
    "S055": "S063",  # Soitec-GlobalFoundries / RF-SOI
}


# 设备侧复用需求侧的一手项目证据时，保留需求研究已经逐条核验的原文定位。
# 这里按设备包内的新 ref 映射，避免复制后退回“原始网页所列段落”的泛定位。
DEMAND_DRIVER_SOURCE_LOCATORS: dict[str, str] = {
    "S055": "PDF正文检索：three new fabs；two advanced packaging facilities；US$165 billion",
    "S056": "网页Idaho expansion时间线检索：initial DRAM output；2027",
    "S057": "网页正文检索短语：M15X；약 20조원；HBM 수요",
    "S058": "SEC文件全文检索：M15X；wafer input began in the first quarter of 2026",
    "S059": "PDF Q&A检索：investing in production equipment within the existing facility",
    "S060": "网页政府答复检索：长江存储三期；总投资超过2700亿元",
    "S061": "PDF募投项目与在建工程检索：2026年6月30日；345亿元；不新建产线",
    "S062": "网页正文检索短语：Investitionsvolumen beträgt fünf Milliarden Euro；Smart Power Fab",
    "S063": "网页新闻稿正文检索：commitment to deliver 300mm RF-SOI substrates；9SW",
}


# 财务代理的原始审计底稿是跨需求侧、设备侧共享的只读输入。设备包在规范化后
# 只补充可复核定位和已核验日期，不回写共享底稿，也不改变其财务数值。
FINANCIAL_SOURCE_OVERRIDES: dict[str, dict[str, str]] = {
    "FIN-JS-01": {
        "local_locator": (
            "2025年年报PDF第8页‘主要会计数据和财务指标’；第10—11页‘半导体装备—半导体集成电路装备’；"
            "第72—73页合并利润表；第75—76页合并现金流量表。检索‘11,357,487,102.93’、"
            "‘硅片制造端’、‘均已实现批量销售’和‘559,207,780.17’。"
        ),
    },
    "FIN-JS-02": {
        "local_locator": (
            "2024年年报‘主要会计数据和财务指标’、合并利润表及合并现金流量表；检索"
            "‘17,576,612,657.90’、‘17,983,185,712.27’、‘3,087,793,255.29’和‘2,474,737,527.06’。"
        ),
    },
    "FIN-ACC-01": {
        "local_locator": (
            "ACCRETECH网页Financial Statements：Consolidated Statements of Income与Consolidated Statements of Cash Flows，"
            "FY2025/03、FY2024/03、FY2023/03三列；检索150,534、62,453、29,703、25,637、28,824和10,245。"
        ),
    },
    "FIN-ACC-02": {
        "local_locator": "ACCRETECH Investor Relations FAQ的‘Stock’小节；检索‘Stock code’、‘7729’和‘Prime Market’。",
    },
    "FIN-ACC-03": {
        "local_locator": (
            "Integrated Report 2025印刷页6产品组合表；检索‘Silicon Wafer Edge Grinder’和"
            "‘Wafer Demounting and Cleaning Machine’。"
        ),
    },
    "FIN-PVA-01": {
        "local_locator": (
            "Annual Report 2025 PDF第101页Semiconductor Systems订单段；第141页Consolidated income statement；"
            "第143页Consolidated cash flow statement；第189页Segment result。检索185.3、244,257、77,848、7,626、"
            "11,805、25,536和Semiconductor Systems 156,624。"
        ),
    },
    "FIN-PVA-02": {
        "local_locator": (
            "PVA TePla临时公告PDF第1页，发布日期2021-08-27；检索‘around EUR 95 million’、"
            "‘Siltronic AG’和‘crystal growing systems for the manufacture of semiconductor silicon wafers’。"
        ),
        "publish_date": "2021-08-27",
        "event_date": "2021-08-27",
    },
    "FIN-PVA-03": {
        "url": "https://www.pvatepla.com/fileadmin/sitepackage/pdf/investor_relations/hauptversammlung/2025/EN/14-Annual_Report_2023.pdf",
        "local_locator": (
            "Annual Report 2023 PDF第4—5页‘Digitization／Computers’产品说明；合并利润表检索263,446；"
            "合并现金流量表检索‘Cash flow from operating activities 1,998’。"
        ),
    },
    "FIN-PVA-04": {
        "local_locator": (
            "Annual Report 2024 PDF第139页Consolidated Income Statement及第141页Consolidated Cash Flow Statement；"
            "检索270,115、263,446、88,035、77,507、27,068、24,421、46,184、1,998、24,156和11,266。"
        ),
    },
    "FIN-PVA-05": {
        "local_locator": (
            "PVA TePla官网Investor Relations—The Share—Share Information表；检索WKN 746100、"
            "ISIN DE0007461006、Ticker symbol TPE和Prime Standard。"
        ),
    },
    "FIN-KLA-01": {
        "local_locator": (
            "KLA 2025 Form 10-K：Consolidated Statements of Operations检索Total revenues 12,156,162；"
            "Consolidated Statements of Cash Flows检索Capital expenditures 335,259；封面检索NASDAQ与KLAC。"
        ),
    },
    "FIN-KLA-02": {
        "local_locator": (
            "KLA新闻稿2018-07-10正文第二段；检索‘Surfscan SP7 system delivers’、‘bare wafers’和"
            "‘essential for manufacturing silicon substrates’。"
        ),
    },
}


# 这些文本均是从对应网页或PDF逐字摘录的原文；中文字段只承担忠实翻译，
# 不再把研究者概括伪装成 source excerpt。其余有数据点的来源在构建时直接
# 复用已通过逐条证据审计的数据点原文；结构化行情/财务接口则保留冻结记录。
DIRECT_SOURCE_EXCERPT_OVERRIDES: dict[str, dict[str, str]] = {
    "S019": {
        "excerpt": (
            "In the United States, the Missouri fab began pilot production earlier this year, "
            "with SOI wafer sampling underway and mass production targeted for 2026. The new "
            "Texas plant (GWA) is actively conducting product qualifications with customers and "
            "will gradually ramp up capacity in response to U.S. localization demand. The site "
            "has entered the sampling and small-batch shipment phase."
        ),
        "excerpt_zh": (
            "在美国，密苏里工厂已于年内开始试产，SOI晶圆正在送样，目标于2026年量产；"
            "得州新厂正在与客户开展产品验证，并将根据美国本地化需求逐步爬坡；相关基地已进入送样和小批量出货阶段。"
        ),
    },
    "S028": {
        "excerpt": "8-12英寸大硅片全产业链设备 晶体生长、切片、抛光、清洗、外延等环节全覆盖，是国内唯一能规模化制造的企业",
        "excerpt_zh": "8—12英寸大硅片全产业链设备覆盖晶体生长、切片、抛光、清洗、外延等环节；‘国内唯一’是公司官网自述。",
    },
    "S031": {
        "excerpt": (
            "The removal rate is efficient and stable, and the process combination is flexible, "
            "which can realize the global flattening of the wafer at the nanometer level, meet "
            "the needs of advanced manufacturing technology, and is widely used in integrated "
            "circuits, advanced packaging, large silicon wafer and other manufacturing processes."
        ),
        "excerpt_zh": "该设备用于纳米级晶圆全局平坦化，公开应用包括集成电路、先进封装和大硅片等制造工艺。",
    },
    "S032": {
        "excerpt": "It has been widely applied in manufacturing processes such as integrated circuits, advanced packaging, and large silicon wafers.",
        "excerpt_zh": "该设备广泛应用于集成电路、先进封装和大硅片等制造工艺。",
    },
    "S033": {
        "excerpt": (
            "华海清科基于自身晶圆清洗技术开发的用于SiC清洗的HSC-S1300清洗装备和用于大硅片终端清洗的"
            "HSC-F3400清洗装备先后验证通过并实现销售，已形成多个制造领域的系列清洗装备，进一步加强了"
            "集成电路制造上游产业链自主可控发展。"
        ),
        "excerpt_zh": (
            "华海清科披露HSC-F3400大硅片终端清洗装备已验证通过并实现销售；该披露没有给出客户名称、复购或专题收入。"
        ),
    },
    "S034": {
        "excerpt": (
            "The Surfscan® SP7 system delivers unprecedented defect detection sensitivity on bare "
            "wafers, smooth and rough films—essential for manufacturing silicon substrates intended "
            "for the 7nm logic and advanced memory device nodes, and equally critical for earliest "
            "detection of process issues during chip manufacturing."
        ),
        "excerpt_zh": "Surfscan SP7用于裸晶圆及光滑、粗糙薄膜的缺陷检测，面向7纳米逻辑和先进存储节点的硅衬底制造。",
    },
    "S035": {
        "excerpt": (
            "Wafer defect inspection, review and metrology systems are used to help wafer/substrate "
            "manufacturers manage quality throughout the wafer fabrication process by detecting "
            "defects, characterizing surface quality and assessing wafer geometry."
        ),
        "excerpt_zh": "晶圆缺陷检测、复检和量测系统帮助晶圆／衬底制造商检测缺陷、表征表面质量并评估晶圆几何形貌。",
    },
    "S036": {
        "excerpt": "Centura Epi is a production-proven, single-wafer, multi-chamber epitaxial silicon deposition product for 150mm and 200mm applications.",
        "excerpt_zh": "Centura Epi是用于150毫米和200毫米应用、经量产验证的单片多腔硅外延沉积产品。",
    },
    "S037": {
        "excerpt": "Silicon epitaxy (Si Epi) is used for depositing precisely controlled crystalline silicon-based layers, a critical process technology for creating advanced transistors and memories.",
        "excerpt_zh": "硅外延用于沉积精确受控的晶体硅基层，是制造先进晶体管和存储器的关键工艺。",
    },
    "S038": {
        "excerpt": "Hesper I E430R 12英寸单片减压硅外延系统 Hesper E230A 12英寸单片常压硅外延系统",
        "excerpt_zh": "公司产品清单列有Hesper I E430R 12英寸单片减压硅外延系统和Hesper E230A 12英寸单片常压硅外延系统。",
    },
    "S039": {
        "excerpt": "硅薄膜外延设备已实现4英寸到12英寸全覆盖，累计销售突破千腔。",
        "excerpt_zh": "公司披露硅薄膜外延设备已覆盖4—12英寸，累计销售超过一千腔；该口径并非硅片厂专用订单。",
    },
    "S040": {
        "excerpt": (
            "Faster crystal growth—Our systems are achieving some of the fastest crystal growth speeds "
            "in the industry, to speeds of 1.6 - 2.0 mm per minute. Hotzone sizes range from 20 to 40 "
            "inches optimized for 200mm, 250mm and 300mm wafers (custom - capable of accommodating other sizes)."
        ),
        "excerpt_zh": "设备拉速可达每分钟1.6—2.0毫米，热场尺寸20—40英寸，可针对200、250和300毫米晶圆优化。",
    },
    "S041": {
        "excerpt": "Single Crystal Silicon Ingot Puller FT-CZ1200Se/1400Se — apparatus for producing semiconductor-grade single-crystal ingots.",
        "excerpt_zh": "FT-CZ1200Se/1400Se单晶硅锭炉用于生产半导体级单晶锭。",
    },
    "S042": {
        "excerpt": (
            "Crystals are used to make wafers from which semiconductors for computing and other digital "
            "applications are sliced. Our crystal growing systems are primarily used to grow silicon "
            "crystals for applications such as memory and processor chips."
        ),
        "excerpt_zh": "晶体被切成用于计算及其他数字应用半导体的晶圆；公司的长晶系统主要用于生长存储和处理器芯片所需硅晶体。",
        "url": "https://www.pvatepla.com/fileadmin/sitepackage/pdf/investor_relations/hauptversammlung/2025/EN/14-Annual_Report_2023.pdf",
    },
    "S043": {
        "excerpt": "DISCO has developed DFG8541, a fully automatic grinder that can process Si (silicon) and SiC (silicon carbide) wafers up to a maximum size of ø8 inches.",
        "excerpt_zh": "DISCO开发的DFG8541全自动研磨机可加工最大8英寸的硅和碳化硅晶圆。",
    },
    "S044": {
        "excerpt": "Model EAC is a bevel polishing system that removes defects and unneeded membranes from the wafer top edge and backside edge.",
        "excerpt_zh": "EAC是用于去除晶圆上边缘和背面边缘缺陷及多余薄膜的倒角抛光系统。",
    },
    "S045": {
        "excerpt": (
            "The investment, including the acquisition of the land, is expected to amount to about ¥83 "
            "billion yen at the completion of the first phase of construction. The new base will produce "
            "semiconductor lithography materials such as photomask blanks, ArF photoresists, multilayer "
            "materials, extreme ultraviolet (EUV) resists and others."
        ),
        "excerpt_zh": "一期完成时投资预计约830亿日元；新基地生产光掩模坯料、ArF光刻胶、多层材料和EUV光刻胶等半导体光刻材料。",
    },
    "S046": {
        "excerpt": (
            "BERNIN 3 Installed: ~350 kwpy Full fab: ~700 kwpy. SINGAPORE PASIR RIS Installed: "
            "~800 kwpy / Full fab: ~2,000 kwpy. Progressive deployment in line with customer demand in qualification."
        ),
        "excerpt_zh": "Bernin 3已安装约35万片／年、满配约70万片／年；新加坡Pasir Ris已安装约80万片／年、满配约200万片／年，后续随验证中的客户需求部署。",
    },
    "S047": {
        "excerpt": "SK Siltron plans to invest USD 1.8 billion in the Gumi National Industrial Complex by 2026 to expand 300mm wafer capacity.",
        "excerpt_zh": "SK Siltron计划到2026年在龟尾国家产业园区投资18亿美元，扩充300毫米硅晶圆产能。",
    },
    "S052": {
        "excerpt": "无图形晶圆缺陷检测设备系列",
        "excerpt_zh": "中科飞测官网产品中心列有‘无图形晶圆缺陷检测设备系列’，但没有披露本轮硅片厂的具名订单。",
    },
    "FIN-ACC-02": {
        "excerpt": "Stock code: 7729. Stock exchange listing: Prime Market of the Tokyo Stock Exchange.",
        "excerpt_zh": "股票代码为7729，上市板块为东京证券交易所Prime市场。",
    },
    "FIN-ACC-03": {
        "excerpt": (
            "Processing equipment: silicon wafer fabrication; Polish grinder; Sliced wafer demounting "
            "and cleaning machine. This machine grinds the front and rear surfaces of wafers with high "
            "precision and then polishes the surfaces to make them flat and smooth."
        ),
        "excerpt_zh": "产品组合包含硅片制造用抛光研磨设备，以及切片后晶圆脱片与清洗设备。",
    },
    "FIN-PVA-01": {
        "excerpt": "In the Semiconductor Systems segment, order intake increased to EUR 185.3 million (previous year: EUR 98.8 million) and accounted for approximately 69% (previous year: 66%) of total order intake.",
        "excerpt_zh": "半导体系统分部2025年新增订单增至1.853亿欧元，上一年为0.988亿欧元，占集团新增订单约69%。",
    },
    "FIN-PVA-02": {
        "excerpt": "PVA Crystal Growing Systems GmbH, a 100% subsidiary of PVA TePla AG (ISIN DE0007461006), today received an order worth EUR 95 million from Siltronic AG to supply crystal growing systems for the production of silicon wafers for the semiconductor industry.",
        "excerpt_zh": "PVA TePla全资子公司获得Siltronic价值0.95亿欧元的订单，供应半导体硅片生产用长晶系统。",
    },
    "FIN-PVA-03": {
        "excerpt": (
            "Crystals are used to make wafers from which semiconductors for computing and other digital "
            "applications are sliced. Our crystal growing systems are primarily used to grow silicon "
            "crystals for applications such as memory and processor chips."
        ),
        "excerpt_zh": "晶体被切成用于计算及其他数字应用半导体的晶圆；公司的长晶系统主要用于生长存储和处理器芯片所需硅晶体。",
    },
    "FIN-PVA-05": {
        "excerpt": "WKN 746100; ISIN DE0007461006; Ticker symbol TPE; Market / Segment Regulated Market / Prime Standard.",
        "excerpt_zh": "WKN为746100，ISIN为DE0007461006，股票代码为TPE，市场板块为受监管市场Prime Standard。",
    },
    "FIN-KLA-02": {
        "excerpt": (
            "The Surfscan® SP7 system delivers unprecedented defect detection sensitivity on bare wafers, "
            "smooth and rough films—essential for manufacturing silicon substrates intended for the 7nm "
            "logic and advanced memory device nodes."
        ),
        "excerpt_zh": "Surfscan SP7用于裸晶圆及光滑、粗糙薄膜的缺陷检测，面向7纳米逻辑和先进存储节点的硅衬底制造。",
    },
}


DIRECT_FINANCIAL_TABLE_REFS = {
    "FIN-JS-01",
    "FIN-JS-02",
    "FIN-ACC-01",
    "FIN-ACC-02",
    "FIN-ACC-03",
    "FIN-PVA-01",
    "FIN-PVA-02",
    "FIN-PVA-03",
    "FIN-PVA-04",
    "FIN-PVA-05",
    "FIN-KLA-01",
    "FIN-KLA-02",
}


PUBLIC_ALIAS_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("上海超硅-供应商B1", "上海超硅-招股书匿名研磨设备供应商"),
    ("匿名供应商B1", "招股书匿名研磨设备供应商"),
    ("供应商B1", "招股书匿名研磨设备供应商"),
    ("日本精工类设备商（需逐项目确认）", "本轮未形成可核验的具名供应商"),
    ("日本精工相关设备企业", "一项无法唯一识别的日本设备候选"),
    ("核心下限模型", "公开可量化项目情景子集"),
    ("下限模型", "公开可量化项目情景子集"),
    ("WSPM", "新增月产能（片/月）"),
    ("PE_TTM", "滚动市盈率（PE-TTM）"),
    ("PS_TTM", "滚动市销率（PS-TTM）"),
    ("EPS_TTM", "滚动每股收益（EPS-TTM）"),
)


def _humanize_public_aliases(value: Any) -> Any:
    if isinstance(value, str):
        result = value
        # Replace the longest aliases first so an alias that is a suffix of
        # another one (for example PS_TTM inside EPS_TTM) cannot corrupt the
        # longer token before it is translated.
        for old, new in sorted(PUBLIC_ALIAS_REPLACEMENTS, key=lambda item: len(item[0]), reverse=True):
            result = result.replace(old, new)
        return result
    if isinstance(value, list):
        return [_humanize_public_aliases(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_humanize_public_aliases(item) for item in value)
    if isinstance(value, dict):
        return {key: _humanize_public_aliases(item) for key, item in value.items()}
    return value


SUPPLEMENTAL_DATA_POINTS: tuple[dict[str, Any], ...] = (
    {
        "id": "DP142",
        "entity": "台积电美国先进逻辑扩产",
        "metric": "AI与先进逻辑扩产方向",
        "period": "2025规划",
        "value": "新增三座晶圆厂、两座先进封装设施和一座研发中心",
        "unit": "项目状态",
        "fact_type": "observed",
        "source_ids": ["S055"],
        "note": "总投资含晶圆厂、封装和研发，不能直接换算硅片月需求或设备额。",
    },
    {
        "id": "DP143",
        "entity": "美光爱达荷州存储项目",
        "metric": "DRAM扩产与初始产出时间",
        "period": "2026公开状态",
        "value": "两座先进存储晶圆厂；首厂预计2027年开始初始DRAM产出",
        "unit": "项目状态",
        "fact_type": "observed",
        "source_ids": ["S056"],
        "note": "没有公开新增月产能（片/月），不能据此估算硅片厂设备台数。",
    },
    {
        "id": "DP144",
        "entity": "SK海力士M15X",
        "metric": "DRAM与HBM产能规划",
        "period": "2024规划",
        "value": "M15X规划用于DRAM/HBM产能扩充",
        "unit": "项目状态",
        "fact_type": "observed",
        "source_ids": ["S057"],
        "note": "这是规划时点的用途证据；不能替代后续晶圆投入状态，也不能把HBM堆叠层数重复乘入晶圆开工量。",
    },
    {
        "id": "DP145",
        "entity": "SK海力士M15X",
        "metric": "晶圆投入与爬坡状态",
        "period": "2026年一季度",
        "value": "开始晶圆投入并逐步爬坡",
        "unit": "项目状态",
        "fact_type": "observed",
        "source_ids": ["S058"],
        "note": "当前进展单独绑定2026来源，不从2024规划自动继承。",
    },
    {
        "id": "DP146",
        "entity": "铠侠Y7与K2",
        "metric": "NAND扩产方式",
        "period": "2026投资者日",
        "value": "优先使用既有洁净室；新厂房视市场在2029年以后考虑",
        "unit": "项目策略",
        "fact_type": "observed",
        "source_ids": ["S059"],
        "note": "NAND位需求增长不能直接等同新增硅片面积或完整线设备需求。",
    },
    {
        "id": "DP147",
        "entity": "长江存储三期",
        "metric": "项目建设状态",
        "period": "2025公开状态",
        "value": "三期项目在建",
        "unit": "项目状态",
        "fact_type": "observed",
        "source_ids": ["S060"],
        "note": "公开资料缺少同口径月产能，仅作为需求方向而非设备金额输入。",
    },
    {
        "id": "DP148",
        "entity": "长鑫相关在建资产",
        "metric": "预计达到预定可使用或可转固状态时间",
        "period": "2026公开状态",
        "value": "预计2026年中达到预定可使用或可转固状态",
        "unit": "项目状态",
        "fact_type": "observed",
        "source_ids": ["S061"],
        "note": "该时点不等于月产能、晶圆需求或硅片设备订单。",
    },
    {
        "id": "DP149",
        "entity": "英飞凌德累斯顿智能功率晶圆厂",
        "metric": "300毫米功率半导体扩产",
        "period": "2026",
        "value": "300毫米智能功率晶圆厂投产",
        "unit": "项目状态",
        "fact_type": "observed",
        "source_ids": ["S062"],
        "note": "只能支持功率应用需求方向，不能反推特定硅片或设备供应商。",
    },
    {
        "id": "DP150",
        "entity": "Soitec与GlobalFoundries",
        "metric": "300毫米RF-SOI应用合作",
        "period": "2024",
        "value": "Soitec供应300毫米RF-SOI衬底以支持GlobalFoundries 9SW平台",
        "unit": "合作状态",
        "fact_type": "observed",
        "source_ids": ["S063"],
        "note": "历史应用合作不能证明2026—2030新增设备订单。",
    },
    {
        "id": "DP151",
        "entity": "上海超硅SOI工艺",
        "metric": "氢离子注入剥离型SOI专有工序",
        "period": "2026招股书研发披露",
        "value": "氧化膜生长、氢离子注入、硅片键合、高温退火剥离、表面平坦化减薄、剥离片表面处理与再键合",
        "unit": "工艺序列",
        "fact_type": "observed",
        "source_ids": ["S004"],
        "source_excerpt": "通过对硅片氧化膜生长、氢离子注入、硅片键合、高温退火剥离、表面平坦化减薄，以及剥离片表面处理再键合等300mm氢离子注入剥离制备绝缘体上硅成套技术方向的深入研究，实现制造300mm SOI产品的技术能力。",
        "note": "这是工艺链证据，不代表任何外部设备商已经取得订单。",
    },
    {
        "id": "DP152",
        "entity": "浙江芯晖装备与西安芯晖设备",
        "metric": "法人和设备业务边界",
        "period": "2025-08-07招股书上会稿",
        "value": (
            "浙江芯晖装备技术有限公司负责电子级硅片研磨/抛光等设备；"
            "西安芯晖设备技术有限公司（曾用名西安奕斯伟设备技术有限公司）定位12英寸硅片拉晶设备"
        ),
        "unit": "法人边界",
        "fact_type": "observed",
        "source_ids": ["S064"],
        "source_excerpt": LEGAL_ENTITY_SOURCE["excerpt"],
        "note": "两个法人不得在数据点、供应关系、因子或标的分析中合并。",
    },
    {
        "id": "DP153",
        "entity": "全球硅晶圆市场",
        "metric": "出货面积",
        "period": "2020-2024",
        "value": None,
        "unit": "百万平方英寸",
        "fact_type": "observed_series",
        "observations": [
            {"period": "2020", "value": 12407},
            {"period": "2021", "value": 14165},
            {"period": "2022", "value": 14713},
            {"period": "2023", "value": 12602},
            {"period": "2024", "value": 12266},
        ],
        "source_ids": ["S065"],
        "source_excerpt": HISTORICAL_CYCLE_SOURCE["excerpt"],
        "source_excerpt_zh": HISTORICAL_CYCLE_SOURCE["excerpt_zh"],
        "note": "该序列用于识别行业周期，不能直接换算任何项目的设备数量或订单。",
    },
    {
        "id": "DP154",
        "entity": "全球硅晶圆市场",
        "metric": "销售额",
        "period": "2020-2024",
        "value": None,
        "unit": "十亿美元",
        "fact_type": "observed_series",
        "observations": [
            {"period": "2020", "value": 11.2},
            {"period": "2021", "value": 12.6},
            {"period": "2022", "value": 13.8},
            {"period": "2023", "value": 12.3},
            {"period": "2024", "value": 11.5},
        ],
        "source_ids": ["S065"],
        "source_excerpt": HISTORICAL_CYCLE_SOURCE["excerpt"],
        "source_excerpt_zh": HISTORICAL_CYCLE_SOURCE["excerpt_zh"],
        "note": "销售额与出货面积结合判断量价周期；不能当作设备市场规模。",
    },
)


FACTOR_NOTES = {
    "demand.downstream_price_momentum": (
        "硅片价格与项目经济性",
        "硅片出货恢复而收入承压，设备需求必须由利用率、售价和客户验证共同确认，不能只看面积增长。",
    ),
    "demand.customer_capex_capacity_signal": (
        "硅片厂资本开支与新增产能",
        "武汉等项目的开工、设备搬入和分期资本开支是需求落地的直接信号，远期投资意向只进入条件判断。",
    ),
    "demand.output_consumption_proxy": (
        "单位产能设备消耗",
        "已投产整线和具名设备合同用于校准单位月产能的设备投入，避免用芯片厂总投资替代硅片设备需求。",
    ),
    "demand.application_intensity_change": (
        "高规格产品的设备价值量",
        "薄层外延、先进逻辑和存储用硅片提高外延、抛光、终洗及检测强度，但不同产线边界必须分开。",
    ),
    "supply.capacity_event_12m": (
        "未来一年交付和验收",
        "2026年四季度武汉设备搬入、立昂微续建和既有海外项目爬坡决定近端订单节奏。",
    ),
    "supply.expansion_cycle_bucket": (
        "设备验证和扩产周期",
        "硅片设备从合同到稳定量产要经过交付、调试、转固和最终验收，技术问题会把收入确认向后推。",
    ),
    "supply.raw_policy_constraint": (
        "贸易、补贴与关键部件约束",
        "进口设备依赖、政府补贴条件、汇率和关键部件供给改变项目可服务范围，但不能替代客户采购证据。",
    ),
    "supply.supplier_structure_bucket": (
        "合格供应商结构",
        "高规格长晶、抛光、外延和无图形检测仍由少数合格供应商参与，国产设备在不同工序成熟度差异很大。",
    ),
    "supply.substitution_barrier": (
        "客户认证与量产稳定性",
        "设备获得试用或付款并不等于最终验收，平整度、缺陷、颗粒和稼动率决定能否替代既有供应商。",
    ),
    "signal.material_price_momentum": (
        "设备订单与价格确认",
        "公开资料缺少统一设备价格指数，因此用具名合同、采购单价、订单和资本开支节奏交叉验证。",
    ),
}


FACTOR_PUBLIC_FRAMES: dict[str, dict[str, str]] = {
    "demand.downstream_price_momentum": {
        "question": "硅片价格和行业收入能否支撑设备采购",
        "evidence_lens": "全球硅片销售额、出货面积、客户利用率与项目经济性",
        "conclusion": "量增尚未转成稳定价增，新增设备不能只靠出货面积增长来判断",
        "risk_test": "若售价继续承压且现有产线仍有闲置能力，项目业主会优先消化旧产能",
        "follow_up": "同口径硅片售价、利用率和项目回报测算",
    },
    "demand.customer_capex_capacity_signal": {
        "question": "硅片厂是否已经把扩产计划推进到设备采购前",
        "evidence_lens": "项目开工、资金落实、设备搬入和新增月产能节点",
        "conclusion": "武汉设备搬入等近端节点比远期投资总额更能约束采购时点",
        "risk_test": "若融资、厂房或设备搬入继续推迟，订单和收入确认都会后移",
        "follow_up": "采购公告、设备搬入清单和分期资本开支",
    },
    "demand.output_consumption_proxy": {
        "question": "每一单位有效新增产能需要投入多少设备",
        "evidence_lens": "完整线设备投入、瓶颈月产能和具名设备合同",
        "conclusion": "目前只能用已投产整线与合同校准数量级，不能从晶圆厂总投资直接推台数",
        "risk_test": "若项目通过改造瓶颈而非新增完整线扩产，单位产能设备投入会明显下降",
        "follow_up": "单机节拍、设备综合效率、良率和备机率",
    },
    "demand.application_intensity_change": {
        "question": "高规格硅片是否会提高这一工序的设备价值量",
        "evidence_lens": "先进逻辑、存储、外延和工程衬底对工艺步骤与质量控制的差异",
        "conclusion": "高规格产品会增加部分工序强度，但不同硅片品类不能套用同一设备组合",
        "risk_test": "若新增需求集中在普通规格或沿用既有工艺，单片设备价值量不会同步提升",
        "follow_up": "各项目产品结构、关键规格和分工序设备清单",
    },
    "supply.capacity_event_12m": {
        "question": "未来十二个月哪些项目最可能形成交付和验收",
        "evidence_lens": "设备搬入、在建工程转固、试产送样和量产爬坡",
        "conclusion": "近端机会集中在已给出搬入或转固节点的项目，远期规划暂不视为订单",
        "risk_test": "若客户认证或厂务进度落后，设备即使交付也可能无法按期验收",
        "follow_up": "逐月搬入、安装、转固和验收记录",
    },
    "supply.expansion_cycle_bucket": {
        "question": "从签约到稳定量产通常会跨越多久",
        "evidence_lens": "合同、交付、调试、转固、最终验收和量产之间的时间差",
        "conclusion": "硅片设备收入存在明显跨期，签约或付款均不能替代最终验收",
        "risk_test": "若工艺调试反复或产品认证失败，收入可能跨年度甚至被取消",
        "follow_up": "合同里程碑、验收条件和收入确认政策",
    },
    "supply.raw_policy_constraint": {
        "question": "贸易政策、补贴和关键部件会怎样改变可服务市场",
        "evidence_lens": "进口依赖、补贴条件、本地化要求、汇率和关键部件供应",
        "conclusion": "政策会改变采购边界和国产替代节奏，但不能代替客户对设备性能的验证",
        "risk_test": "若关键部件受限或补贴条件收紧，交付成本和项目节奏可能恶化",
        "follow_up": "受限部件清单、原产地要求和补贴兑现条件",
    },
    "supply.supplier_structure_bucket": {
        "question": "这一工序有多少真正通过验证的供应商",
        "evidence_lens": "具名客户、产品尺寸、量产交付和同工序竞争者",
        "conclusion": "供应格局在不同工序差异很大，产品页存在不等于进入合格供应商名单",
        "risk_test": "若客户继续集中采购成熟进口平台，国产厂商可获得份额会低于产品覆盖所暗示的水平",
        "follow_up": "合格供应商名单、复购记录和竞争性招标结果",
    },
    "supply.substitution_barrier": {
        "question": "新供应商能否通过客户认证并保持量产稳定",
        "evidence_lens": "缺陷、颗粒、平整度、良率、稼动率与最终验收",
        "conclusion": "试用、付款和转固只证明阶段进展，持续量产与复购才证明替代成立",
        "risk_test": "若核心质量指标波动或维护成本过高，客户会回到既有供应商",
        "follow_up": "量产质量数据、停机记录、最终验收和复购",
    },
    "signal.material_price_momentum": {
        "question": "订单金额和设备价格是否已经出现可验证改善",
        "evidence_lens": "具名合同、采购单价、新增订单、交付与资本开支节奏",
        "conclusion": "没有统一设备价格指数时，只能用合同和订单交叉判断价格与需求变化",
        "risk_test": "若订单只来自低价试用或一次性历史项目，不能据此推断持续提价",
        "follow_up": "同型号合同价格、订单结构、交付数量和回款",
    },
}


ENTITY_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "semiconductor_crystal_growth_tools",
        "name": "半导体单晶生长设备",
        "description": "覆盖300毫米和200毫米电子级硅片直拉单晶炉、热场及与晶体生长直接相关的系统，不把光伏长晶设备混入。",
        "base_score": 70,
        "refs": ["S066", "S011", "S014", "S028", "S029", "S079", "S040", "S041", "FIN-PVA-02", "FIN-PVA-06"],
        "focus": "武汉完整产线和SUMCO分期晶体项目为新增需求，国内外供应商已有历史交付，但武汉设备品牌和炉台数尚未披露",
        "method": "先用项目产能与整线设备预算确定金额边界，再等炉次、晶锭有效长度、良率、热场寿命和设备综合效率齐备后估算台数；本轮不以拉速单参数制造精确台数",
        "competition": "晶盛机电与晶升股份具备国内交付证据，PVA TePla有对Siltronic的历史大额订单，Linton和Ferrotec有直接产品；历史客户关系不能自动升级为武汉订单",
        "financial": "晶盛机电合并收入含大量光伏装备和材料，PVA TePla半导体系统也不只服务硅片，因此财务弹性只能在硅片专用订单单列后量化",
        "risk": "若硅片厂优先提高现有炉台利用率、武汉采购后移，或国产炉在稳定性与寿命上无法通过验收，订单和利润会明显低于项目投资所暗示的空间",
        "follow_up": "武汉环评设备表、单晶炉招标与搬入清单、炉次和良率参数、晶盛与PVA的硅片专用订单及验收收入",
        "targets": ["jingsheng", "pva_tepla"],
    },
    {
        "key": "wafer_grinding_polishing_tools",
        "name": "硅片研磨与抛光设备",
        "description": "覆盖硅锭成型后的研磨、倒角、双面抛光、最终抛光及相关脱片清洗，严格区分硅衬底生产和器件晶圆背面减薄。",
        "base_score": 67,
        "refs": ["S066", "S075", "S076", "S077", "S080", "S081", "S067", "S071", "S011", "S028", "S031", "S032", "S033", "S043", "FIN-ACC-03", "S064"],
        "focus": "上海超硅把抛光设备列为瓶颈，西安奕材的国产CMP已经转固而研磨减薄设备尚未最终验收，说明需求真实但成熟度分化",
        "method": "对研磨设备只做可复算示例：目标月产能除以单台名义月能力并增加检修余量；型号、设备综合效率、良率和备机率不足时不把示例当项目采购量",
        "competition": "东京精密、SpeedFam、Lapmaster Wolters、Okamoto等拥有直接产品或采购证据，浙江芯晖装备和华海清科代表国产验证；DISCO泛晶圆产品不能在缺少12英寸硅衬底证据时自动纳入",
        "financial": "东京精密半导体设备业务同时覆盖多类晶圆加工，合并利润不等于硅片研磨利润；财务观察应结合硅片专用设备订单、分部收入和验收节奏",
        "risk": "光滑度参数稳定性不达标会造成已付款设备长期不转固；若客户通过解除局部瓶颈提升产出，完整线新增设备金额也会被高估",
        "follow_up": "武汉与立昂微研磨抛光清单、最终验收记录、设备综合效率、单机节拍、备机比例及东京精密硅片专用订单",
        "targets": ["accretech"],
    },
    {
        "key": "silicon_epitaxy_tools",
        "name": "硅外延设备",
        "description": "研究200毫米与300毫米硅外延系统及其配套气体控制和缺陷管理，不将普通薄膜沉积设备一概视为硅片制造设备。",
        "base_score": 64,
        "refs": ["S068", "S069", "S073", "S074", "S011", "S024", "S026", "S036", "S037", "S038", "S039", "S046"],
        "focus": "上海超硅15万片/月薄层外延项目披露27.86亿元设备及安装预算，立昂微多个外延项目在建，但融资、开工和延期使兑现时间差异很大",
        "method": "外延专线使用项目自己的设备预算，不套用普通抛光片完整线的单位产能参数；只有资金、正式合同和安装进度出现后才进入较确定订单",
        "competition": "应用材料与上海超硅存在直接合同，ASM和北方华创有产品能力，晶盛机电披露外延设备产品链；后几者与本轮新增项目没有公开具名合同",
        "financial": "可上市跟踪标的多为综合设备公司，硅外延业务占比未单列；投资判断要等外延项目合同额、腔体数量、验收和服务收入，而不是套用集团毛利率",
        "risk": "外延项目可能因行业开工率偏低继续延期，且高价值系统对厚度均匀性、缺陷密度和长期稳定性要求高，产品存在不代表能获得量产份额",
        "follow_up": "上海超硅募资和开工、立昂微外延项目设备合同、武汉是否配置外延、反应腔数量、厚度均匀性与供应商量产验收",
        "targets": ["jingsheng"],
    },
    {
        "key": "bare_wafer_metrology_tools",
        "name": "无图形晶圆检测与量测",
        "description": "覆盖裸硅片表面缺陷、颗粒、几何形貌和平坦度量测，重点判断高规格硅片认证所需的检测能力与供应商壁垒。",
        "base_score": 72,
        "refs": ["S070", "S073", "S011", "S027", "S033", "S034", "S035", "S046", "FIN-KLA-01", "FIN-KLA-02"],
        "focus": "上海超硅披露与KLA的多份检测和量测合同，高规格外延与先进逻辑硅片需要更严的表面和几何控制，但新增项目采购仍需单独确认",
        "method": "市场空间先由有效新增产能和项目设备预算约束，再按检测工序占比和目标规格筛选；缺少设备数量、单价与项目份额时不输出单家公司金额",
        "competition": "KLA的直接合同和裸片产品证据最强，国产检测公司只有明确指向无图形大硅片并完成量产验证后才能进入同一比较层级",
        "financial": "KLA总收入主要来自广泛的制程控制业务，Surfscan等裸片检测只是其中一部分；三年合并财务只能检验交付能力和现金流，不能代表硅片扩产收入弹性",
        "risk": "旧产品页可能高估当前产品代际，客户可能沿用既有进口设备而只新增少量瓶颈工具；国产替代若缺少缺陷灵敏度和复购证据，短期份额难以判断",
        "follow_up": "武汉和上海超硅的检测清单、Surfscan当前代际与单价、国产无图形晶圆检测量产记录、复购和服务合同",
        "targets": ["kla"],
    },
    {
        "key": "wafer_final_clean_automation",
        "name": "硅片终洗与自动化",
        "description": "覆盖大硅片最终清洗、脱片清洗、自动上下料、厂内传输与整线接口，关注颗粒控制和与既有产线的集成难度。",
        "base_score": 55,
        "refs": ["S001", "S075", "S076", "S004", "S010", "S011", "S018", "S019", "S031", "S032", "S033", "FIN-ACC-03"],
        "focus": "完整硅片线必须配置终洗与自动化，但公开资料中的具名客户和订单明显少于长晶、抛光、外延与检测，因此属于需要补证的早期机会",
        "method": "当前只确认产品是否明确用于大硅片、是否完成客户验证以及项目是否进入搬入阶段；自动化价值量和供应商份额在整线接口、台套和报价公开前不做数字预测",
        "competition": "华海清科披露大硅片终洗验证和销售，东京精密有用于硅片制造的脱片清洗机；自动化集成商公开客户不足，无法做可靠份额排序",
        "financial": "东京精密和华海清科均有更广泛业务，终洗与自动化收入没有单列；最早的财务确认应是具名合同、存货与合同负债变化、验收以及分部现金回款",
        "risk": "客户可能由整线集成商打包采购或沿用既有自动化平台，公开产品能力也可能停留在单机验证；如果没有复购与稼动率数据，受益判断应保持低置信度",
        "follow_up": "武汉厂内物流与终洗清单、华海清科具名客户和复购、东京精密硅片清洗订单、颗粒指标、整线接口与验收周期",
        "targets": ["accretech"],
    },
)


SEGMENT_ID_BY_ENTITY = {
    "semiconductor_crystal_growth_tools": "SEG1_CRYSTAL_GROWTH",
    "wafer_grinding_polishing_tools": "SEG2_GRIND_POLISH",
    "wafer_final_clean_automation": "SEG3_CLEAN_AUTOMATION",
    "bare_wafer_metrology_tools": "SEG4_INSPECTION_METROLOGY",
    "silicon_epitaxy_tools": "SEG5_EPI_ENGINEERED",
}


EQUIPMENT_FACTOR_ROUTES: dict[str, tuple[int, ...]] = {
    "demand.downstream_price_momentum": (9,),
    "demand.customer_capex_capacity_signal": (0, 1, 8),
    "demand.output_consumption_proxy": (0, 4),
    "demand.application_intensity_change": (3, 4, 7),
    "supply.capacity_event_12m": (0, 1, 5),
    "supply.expansion_cycle_bucket": (5, 8, 9),
    "supply.raw_policy_constraint": (6,),
    "supply.supplier_structure_bucket": (2, 6),
    "supply.substitution_barrier": (3, 5, 6, 7),
    "signal.material_price_momentum": (1, 8, 9),
}


EQUIPMENT_POLICY_GROUPS = (
    "G06_TCL_YIXING",
    "G08_SUMCO_METI",
    "G09_GLOBALWAFERS",
    "G11_SK_SILTRON",
    "G12_SOITEC",
)


EQUIPMENT_FACTOR_SCORES: dict[str, dict[str, int]] = {
    "semiconductor_crystal_growth_tools": {
        "demand.downstream_price_momentum": 55,
        "demand.customer_capex_capacity_signal": 75,
        "demand.output_consumption_proxy": 68,
        "demand.application_intensity_change": 72,
        "supply.capacity_event_12m": 78,
        "supply.expansion_cycle_bucket": 70,
        "supply.raw_policy_constraint": 68,
        "supply.supplier_structure_bucket": 65,
        "supply.substitution_barrier": 75,
        "signal.material_price_momentum": 60,
    },
    "wafer_grinding_polishing_tools": {
        "demand.downstream_price_momentum": 54,
        "demand.customer_capex_capacity_signal": 72,
        "demand.output_consumption_proxy": 66,
        "demand.application_intensity_change": 76,
        "supply.capacity_event_12m": 70,
        "supply.expansion_cycle_bucket": 68,
        "supply.raw_policy_constraint": 62,
        "supply.supplier_structure_bucket": 68,
        "supply.substitution_barrier": 78,
        "signal.material_price_momentum": 58,
    },
    "silicon_epitaxy_tools": {
        "demand.downstream_price_momentum": 52,
        "demand.customer_capex_capacity_signal": 66,
        "demand.output_consumption_proxy": 60,
        "demand.application_intensity_change": 78,
        "supply.capacity_event_12m": 60,
        "supply.expansion_cycle_bucket": 70,
        "supply.raw_policy_constraint": 55,
        "supply.supplier_structure_bucket": 66,
        "supply.substitution_barrier": 82,
        "signal.material_price_momentum": 55,
    },
    "bare_wafer_metrology_tools": {
        "demand.downstream_price_momentum": 55,
        "demand.customer_capex_capacity_signal": 69,
        "demand.output_consumption_proxy": 65,
        "demand.application_intensity_change": 83,
        "supply.capacity_event_12m": 67,
        "supply.expansion_cycle_bucket": 72,
        "supply.raw_policy_constraint": 50,
        "supply.supplier_structure_bucket": 80,
        "supply.substitution_barrier": 88,
        "signal.material_price_momentum": 58,
    },
    "wafer_final_clean_automation": {
        "demand.downstream_price_momentum": 45,
        "demand.customer_capex_capacity_signal": 58,
        "demand.output_consumption_proxy": 55,
        "demand.application_intensity_change": 65,
        "supply.capacity_event_12m": 60,
        "supply.expansion_cycle_bucket": 65,
        "supply.raw_policy_constraint": 62,
        "supply.supplier_structure_bucket": 52,
        "supply.substitution_barrier": 68,
        "signal.material_price_momentum": 47,
    },
}


TARGET_TEXT = {
    "jingsheng": {
        "priority": "P1",
        "quality": "直接产品、项目订单待确认",
        "view": "晶盛机电覆盖从长晶到切磨抛、外延和清洗的多道工序，最值得跟踪武汉项目是否出现具名合同；在硅片专用收入未单列前，不把集团收入变化当作本主题盈利弹性。",
        "risk": "合并业务受光伏装备和材料周期显著影响，硅片设备合同即使落地，也可能不足以抵消其他业务下行；向Okmetic的历史具名交付不能据此推断其他客户或新增项目份额。",
        "confirmed": "武汉或其他新增产线披露正式合同、设备搬入并通过阶段验收，同时半导体设备收入开始单列时提高研究优先级。",
        "falsified": "项目采购后移、订单始终不具名，或设备在良率与稳定性上未通过最终验收时，下调本主题对公司盈利的贡献。",
    },
    "accretech": {
        "priority": "P1",
        "quality": "专用产品明确、客户订单需补",
        "view": "东京精密明确提供硅片边缘磨削及脱片清洗设备，产品边界直接；但公司半导体设备覆盖更广，投资判断需要新增硅片项目订单而非行业资本开支概念。",
        "risk": "硅片专用设备收入未单列，日本及海外客户采购周期也不透明；若新增厂只购买瓶颈设备，集团层面的收入弹性可能很小。",
        "confirmed": "硅片厂披露具名采购、东京精密分部订单加速且交付验收同步后，才把本轮扩产视为可见收入。",
        "falsified": "订单增长主要来自器件晶圆加工而非硅衬底制造，或客户继续使用既有设备消化扩产时，维持普通观察。",
    },
    "pva_tepla": {
        "priority": "P2",
        "quality": "历史客户直接、当前订单待补",
        "view": "PVA TePla曾获得Siltronic半导体硅片长晶系统大额订单，直接性强；当前需要用2026—2030新增订单替换2021年的历史关系。",
        "risk": "半导体系统分部仍含其他应用，历史0.95亿欧元订单已在此前年度执行，不能重复计入本轮市场或收入。",
        "confirmed": "SUMCO、GlobalWafers、Siltronic或中国新线披露新的长晶系统合同并给出交付期后，上调当前机会判断。",
        "falsified": "新增项目由其他供应商承接或长晶投资继续延后，同时半导体系统订单下行时，历史客户证据不再提供当前催化。",
    },
    "kla": {
        "priority": "P1",
        "quality": "客户合同直接、集团暴露很小",
        "view": "KLA在裸片缺陷与几何量测上的产品和上海超硅合同证据最直接，但硅片制造只占其广泛制程控制业务的一小部分，应关注项目订单而不是集团总增长。",
        "risk": "旧产品资料不能证明当前机型与份额，上海超硅历史合同也不等于武汉或新外延项目订单；集团业绩可能主要由芯片晶圆厂资本开支驱动。",
        "confirmed": "新增硅片项目出现KLA具名合同、复购或服务收入，并与项目搬入和验收节点一致时，提高本主题的业绩可见度。",
        "falsified": "本轮扩产没有新增裸片检测合同，或订单增长仅来自图形晶圆制程控制时，不把硅片设备作为KLA主要投资逻辑。",
    },
}


TARGET_CONDITIONAL_RECOMMENDATIONS = {
    "pva_tepla": (
        "只有新的半导体硅片长晶系统订单同时带来半导体系统新增订单、分部收入或利润改善时，"
        "才上调PVA TePla；2021年Siltronic订单不得重复计算。"
    ),
    "accretech": (
        "只有新增硅片项目出现研磨、抛光或脱片清洗设备具名合同，并能在东京精密订单与验收中对应时，"
        "才评估项目对盈利的增量。"
    ),
    "jingsheng": (
        "只有半导体硅片专用设备的具名订单、客户验证和专题收入同步改善时，才上调晶盛机电；"
        "光伏及其他业务变化不作为本主题确认。"
    ),
    "kla": (
        "只有当前代际裸晶圆检测与量测设备在新增硅片项目获得复购，并与交付、验收相互印证时，"
        "才提高KLA在本主题中的盈利权重。"
    ),
    "crystal_rise": (
        "晶升股份需要同时出现12英寸单晶炉新订单、客户验收、专用收入回升和恢复盈利，"
        "才从业务直接性上升为可见盈利机会。"
    ),
    "applied_materials": (
        "只有新增硅片外延项目披露当前平台的腔体合同、交付与验收，才评估Applied Materials的项目增量；"
        "集团晶圆制造设备增长不能替代该证据。"
    ),
    "huahai_qingke": (
        "只有大硅片终洗或CMP设备出现具名客户复购、最终验收和专用毛利披露时，"
        "才把华海清科从产品验证提升为可量化盈利机会。"
    ),
}


SUPPLEMENTAL_TARGET_DECISIONS = {
    "crystal_rise": {
        "risk": "晶升股份2025年亏损且毛利率降至15.03%；历史客户交付不能替代当前订单，若12英寸单晶炉验证没有转成复购，业务直接性也难以改善盈利。",
        "confirmed": "新增12英寸半导体单晶炉取得具名合同、完成客户验收，专用收入回升并推动公司恢复盈利时上调。",
        "falsified": "客户验证停滞、没有新单晶炉订单或公司继续亏损且毛利率下滑时，下调本主题判断。",
    },
    "applied_materials": {
        "risk": "Applied Materials业务覆盖广泛晶圆制造设备，历史上海超硅常压外延合同不能证明当前项目或当前平台份额。",
        "confirmed": "新增硅片外延项目披露当前平台、腔体数量、合同金额并完成安装验收时，上调项目业绩可见度。",
        "falsified": "新增外延线由其他平台承接，或集团增长主要来自非硅片制造产品时，不把本主题作为主要盈利驱动。",
    },
    "huahai_qingke": {
        "risk": "大硅片终洗虽已验证销售但客户匿名，集团毛利率连续下降；若没有具名复购和专用毛利，产品进展不能直接转成盈利判断。",
        "confirmed": "HSC-F3400终洗或相关大硅片CMP设备出现具名客户复购、最终验收、专用收入和毛利时上调。",
        "falsified": "设备长期停留在匿名销售或单机验证，客户改用其他方案且集团毛利继续下降时，下调本主题判断。",
    },
}


SUPPLEMENTAL_TARGET_ROLE_TEXT = {
    "crystal_rise": {
        "profile": (
            "晶升股份聚焦半导体晶体生长设备，监管材料确认其12英寸单晶炉曾向上海新昇、立昂微等客户交付。"
            "这些事实证明产品和历史客户关系，不证明2026—2030年新增项目已经下单。"
        ),
        "deep": (
            "2023—2025年财务显示，晶升股份2025年收入和毛利率明显下降并转亏，当前市盈率也不适用。"
            "单晶炉新订单只有在交付、终验后形成专用收入和回款，才可能改善盈利；集团报表目前没有把12英寸单晶炉单独列示。"
        ),
        "view": (
            "当前判断是产品直接、历史交付可核验，但当期盈利和新项目订单都偏弱；"
            "具名12英寸单晶炉合同、终验、专用收入回升并恢复盈利时上调，持续无新增订单或继续亏损时下调。"
        ),
    },
    "applied_materials": {
        "profile": (
            "Applied Materials提供硅外延设备，上海超硅招股书披露了两份常压外延系统合同，"
            "公司产品资料也能交叉确认平台能力；历史合同不能替代本轮薄层外延项目订单。"
        ),
        "deep": (
            "FY2022—FY2025合并收入持续增长，但FY2025净利润低于FY2024，当前估值反映的是综合晶圆制造设备业务。"
            "硅片外延专用收入未单列，只有新项目腔体合同经过安装验收并在服务或分部收入中可识别，项目金额才会传到公司财务。"
        ),
        "view": (
            "当前判断是技术与历史客户证据强、当前项目盈利传导不可见；"
            "新外延线披露平台、腔体数量、合同金额和验收时上调，订单由其他平台承接或增长仍来自非硅片业务时不采纳本主题。"
        ),
    },
    "huahai_qingke": {
        "profile": (
            "华海清科覆盖大硅片CMP、研磨和终洗，公司披露HSC-F3400终洗设备已验证并销售。"
            "客户仍未具名，现有材料只能确认产品进入市场，不能确认武汉或立昂微采购。"
        ),
        "deep": (
            "2023—2025年收入和净利润增长，但毛利率连续回落，当前估值也较高；除权后的每股净资产已按上交所送转比例校正。"
            "由于大硅片设备收入和毛利没有单列，匿名销售若不能形成复购、终验和回款，集团增长不能归因于本主题。"
        ),
        "view": (
            "当前判断是产品验证领先于订单和利润证据；"
            "具名客户复购、最终验收及大硅片专用收入和毛利同时出现时上调，长期停留在匿名单机销售或集团毛利继续下降时下调。"
        ),
    },
}


DEMAND_TO_EQUIPMENT_ROWS: tuple[dict[str, Any], ...] = (
    {
        "driver": "AI服务器与先进逻辑扩产",
        "wafer": "300毫米高规格抛光片；部分项目增加退火片或外延片",
        "process": "完整长晶、切磨抛、终洗，并提高表面缺陷与几何量测要求",
        "suppliers": "晶盛机电、晶升股份、PVA TePla；KLA、中科飞测；外延环节另看应用材料、ASM、北方华创",
        "boundary": "晶圆厂投资包含厂房、封装和研发，必须先落到新增月产能（片/月）、硅片采购和硅片厂有效新增产能，不能直接换算设备订单。",
        "refs": ["S055", "S011", "S028", "S034", "S035"],
    },
    {
        "driver": "DRAM与HBM扩产",
        "wafer": "300毫米存储用高规格抛光片",
        "process": "完整抛光片链和严格缺陷检测；是否增加外延或退火工序要由客户规格确认",
        "suppliers": "长晶、切磨抛与检测候选同300毫米完整线",
        "boundary": "HBM是DRAM需求驱动，堆叠层数不能再次乘入晶圆开工量；公开项目没有同口径新增月产能（片/月）。",
        "refs": ["S056", "S057", "S058", "S028", "S035"],
    },
    {
        "driver": "NAND位需求增长",
        "wafer": "300毫米存储用抛光片",
        "process": "只有晶圆投入增加才拉动硅片完整线；单纯提高层数更多消耗既有洁净室与器件工艺设备",
        "suppliers": "暂不因为位需求增速上调硅片设备商排序",
        "boundary": "铠侠明确优先使用既有洁净室，因此NAND位增长不能直接等同硅片面积增长。",
        "refs": ["S059", "S027", "S028"],
    },
    {
        "driver": "长江存储、长鑫等中国存储项目",
        "wafer": "300毫米存储用抛光片，且要通过客户认证",
        "process": "若晶圆厂扩产与国产硅片认证同时兑现，才拉动中国完整长晶、切磨抛、终洗和检测链",
        "suppliers": "中国完整线和检测候选；目前不能由客户名称反推供应商",
        "boundary": "项目方向可确认，但公开资料没有同口径月产能和硅片采购合同，不能量化设备台数。",
        "refs": ["S060", "S061", "S001", "S077"],
    },
    {
        "driver": "功率半导体与汽车电子",
        "wafer": "200毫米及300毫米重掺衬底、轻掺或重掺外延片",
        "process": "重掺单晶、切磨抛、硅外延和外延后膜厚/缺陷检测的价值更高",
        "suppliers": "晶盛机电、晶升股份；应用材料、ASM、北方华创；KLA、中科飞测",
        "boundary": "200毫米、300毫米与外延专线的配置不同，不能套普通300毫米完整线的单位设备强度。",
        "refs": ["S062", "S074", "S036", "S037", "S038", "S039"],
    },
    {
        "driver": "射频与SOI工程衬底",
        "wafer": "300毫米或200毫米SOI工程晶圆",
        "process": "在普通抛光片后增加氧化、离子注入、键合、退火剥离、减薄、终洗与专用量测",
        "suppliers": "公开资料只确认SOI工艺链；本轮没有具名专有设备供应商",
        "boundary": "普通器件晶圆的离子注入、键合或减薄设备不能自动纳入SOI衬底供应链。",
        "refs": ["S063", "S004"],
    },
)


SOI_PROCESS_ROWS: tuple[dict[str, Any], ...] = (
    {"step": "1. 供体片与支撑片制备", "equipment": "长晶、切磨抛、清洗和基础检测", "difference": "沿用普通硅片链，但需按顶层硅和支撑片规格筛选；不构成专有设备增量", "supplier": "沿用普通硅片设备池，不能据此认定SOI项目订单", "refs": ["S004"]},
    {"step": "2. 氧化膜生长", "equipment": "氧化与热处理炉", "difference": "形成绝缘埋层相关结构，温度和膜厚均匀性是新增控制点", "supplier": "本轮没有SOI项目具名设备商", "refs": ["S004"]},
    {"step": "3. 氢离子注入", "equipment": "工程衬底用大束流离子注入系统", "difference": "能量控制分离深度，剂量和温度影响剥离缺陷", "supplier": "上海超硅披露该工艺技术能力，但未披露外部设备合同或设备来源", "refs": ["S004"]},
    {"step": "4. 键合前清洗与硅片键合", "equipment": "高洁净清洗、表面活化、对准与键合设备", "difference": "颗粒和键合界面质量直接影响后续剥离良率", "supplier": "本轮没有SOI项目具名设备商", "refs": ["S004"]},
    {"step": "5. 高温退火与剥离", "equipment": "高温退火炉及剥离过程控制", "difference": "使硅片在氢离子聚集区分离，决定表面缺陷和厚度均匀性", "supplier": "本轮没有SOI项目具名设备商", "refs": ["S004"]},
    {"step": "6. 平坦化、减薄与抛光", "equipment": "研磨、减薄、CMP与最终抛光", "difference": "控制顶层硅厚度、均匀性和剥离损伤，而不只是普通表面平整度", "supplier": "通用大硅片研磨/CMP产品存在，SOI项目订单未公开", "refs": ["S004", "S031", "S032"]},
    {"step": "7. 终洗与表面处理", "equipment": "终洗、干燥、颗粒与金属污染控制", "difference": "清除剥离与平坦化残留并保护键合结构", "supplier": "本轮没有SOI项目具名设备商", "refs": ["S004", "S033"]},
    {"step": "8. SOI层与键合界面量测", "equipment": "层厚、均匀性、表面缺陷、翘曲和界面检测", "difference": "在普通裸片指标外增加SOI层厚和键合/剥离缺陷检查", "supplier": "KLA仅有广义衬底产品与普通检测合同，不能当作SOI新订单", "refs": ["S004", "S034", "S035"]},
    {"step": "9. 剥离片恢复与再利用", "equipment": "表面处理、研磨/抛光、清洗和再检测", "difference": "研发路线包含剥离片处理与再键合，量产良率和循环次数尚未披露", "supplier": "没有具名供应商或设备金额", "refs": ["S004"]},
)


SUPPLIER_DISPOSITION_ROWS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("晶盛机电", "核心", "覆盖半导体长晶、切磨抛、清洗并有Okmetic交付；武汉合同未公开", ("S028", "S029")),
    ("晶升股份", "核心", "上海新昇和立昂微12英寸单晶炉历史验收与批量供货可确认；缺当前项目订单", ("S079",)),
    ("浙江芯晖装备", "核心（非上市）", "独立法人；西安奕材具名采购CMP和研磨减薄设备，CMP已转固，研磨设备尚未完成验收", ("S075", "S076", "S064")),
    ("西安芯晖设备（原西安奕斯伟设备）", "核心（非上市）", "独立法人；西安奕材监管文件确认其12英寸拉晶设备和合同，不能与浙江芯晖装备的研磨/CMP主体混写", ("S077", "S064")),
    ("华海清科", "观察", "大硅片CMP、研磨和终洗产品明确，终洗已销售但客户未具名", ("S031", "S032", "S033")),
    ("北方华创", "观察", "4—12英寸硅外延产品可确认，缺硅片厂具名客户", ("S038", "S039")),
    ("中科飞测", "观察", "无图形晶圆缺陷检测可用于硅片出厂控制，缺目标项目合同和复购", ("S051", "S052")),
    ("精测电子", "排除核心排序", "本轮未找到硅衬底制造产品和具名客户的一手证据", ()),
    ("沈阳科仪", "排除核心排序", "本轮未找到目标200/300毫米硅片产线的产品级或客户级一手证据", ()),
    ("芯源微", "排除核心排序", "已核验清洗产品服务器件晶圆工序，不是硅衬底终洗证据", ("S053",)),
    ("KLA", "核心", "上海超硅具名检测合同和裸硅片质量控制产品证据明确", ("S070", "S034", "S035")),
    ("Applied Materials", "核心", "上海超硅常压外延系统合同可确认；新外延项目尚无采购公告", ("S069", "S036")),
    ("Tokyo Seimitsu / ACCRETECH", "观察", "产品明确用于硅片研磨、边缘成型和脱片清洗；缺本轮项目合同", ("S050",)),
    ("PVA TePla", "核心", "年报确认半导体晶圆长晶系统，历史有Siltronic订单；缺本轮具名订单", ("S042", "FIN-PVA-02")),
    ("ASM International", "观察", "年报确认硅外延能力，缺本轮目标客户和订单", ("S037",)),
    ("Linton Crystal Technologies", "观察", "产品页确认200/250/300毫米长晶能力，缺目标客户", ("S040",)),
    ("Ferrotec", "观察", "硅单晶生长设备能力可确认，缺本轮采购关系", ("S041",)),
    ("SpeedFam", "核心（历史关系）", "上海超硅历史双面抛光设备采购可确认，新项目复购未确认", ("S071",)),
    ("Lapmaster Wolters", "核心（历史关系）", "上海超硅历史双面抛光设备采购可确认，新项目复购未确认", ("S071",)),
    ("Okamoto", "核心（历史关系）", "上海超硅披露与该终端设备生产商直接合作；具体机型和本轮项目合同未披露", ("S081",)),
    ("DISCO", "观察，暂不进12英寸核心排序", "已核验产品最高支持8英寸且用途边界混合，不能外推12英寸整线", ("S043",)),
    ("Ebara", "观察", "边缘与倒角抛光产品明确，但也用于器件晶圆薄膜去除，缺目标项目采购", ("S044",)),
    ("Lam Research", "排除核心排序", "本轮未找到硅衬底制造专用产品和目标硅片厂直接关系", ()),
    ("Tokyo Electron / TEL", "排除核心排序", "本轮未找到硅衬底制造设备或目标项目订单的一手证据", ()),
    ("S-TECH", "观察", "只有2022年发行人材料中的历史格局描述，不能单独证明当前地位", ("S030",)),
    ("SUMCO关联设备供应链", "排除具名排序", "这不是可唯一识别的法人；SUMCO项目没有公开设备品牌", ("S014",)),
    ("一项无法唯一识别的日本设备候选", "排除具名排序", "主体和产品型号无法唯一识别，不能据类别名称补写供应关系", ()),
)


NEGATIVE_SUPPLIER_SEARCH_LOGS: tuple[dict[str, Any], ...] = (
    {
        "candidate": "精测电子",
        "searched_on": AS_OF_DATE,
        "scope": "公司官网产品页、交易所公告、目标硅片厂招股书/问询回复",
        "queries": ["精测电子 硅片制造 裸片 检测", "精测电子 上海超硅 西安奕材 设备"],
        "result": "未找到硅衬底制造产品和目标硅片厂具名关系的一手材料；只据本轮检索排除核心排序。",
    },
    {
        "candidate": "沈阳科仪",
        "searched_on": AS_OF_DATE,
        "scope": "公司官网产品页、科研机构官网、目标200/300毫米硅片厂公开材料",
        "queries": ["沈阳科仪 半导体硅片 200mm 300mm 设备", "沈阳科仪 硅片厂 客户"],
        "result": "未找到可对应目标尺寸与工序的产品级或客户级一手材料；只据本轮检索排除核心排序。",
    },
    {
        "candidate": "Lam Research",
        "searched_on": AS_OF_DATE,
        "scope": "公司官网产品页、监管文件、目标硅片厂公开采购与供应商材料",
        "queries": ["site:lamresearch.com silicon wafer manufacturing equipment substrate", "Lam Research Shanghai Simgui wafer supplier"],
        "result": "找到的是器件晶圆前道平台，没有找到硅衬底制造专用产品或目标硅片厂直接关系。",
    },
    {
        "candidate": "Tokyo Electron / TEL",
        "searched_on": AS_OF_DATE,
        "scope": "公司官网产品页、综合报告、目标硅片厂公开采购与供应商材料",
        "queries": ["site:tel.com silicon wafer manufacturing substrate equipment", "Tokyo Electron silicon wafer maker customer"],
        "result": "找到的是器件晶圆前道产品，没有找到硅衬底制造设备或目标项目订单的一手材料。",
    },
    {
        "candidate": "日本设备类别线索（主体无法唯一识别）",
        "searched_on": AS_OF_DATE,
        "scope": "中英文/日文公司名、设备类别、发行人材料和目标硅片厂采购材料",
        "queries": ["日本精工 硅片 研磨 设备", "NSK semiconductor wafer manufacturing equipment"],
        "result": "类别名称无法唯一对应法人和产品型号，不能据相似名称补写供应关系。",
    },
)


LISTED_COMPANY_RANKING_ROWS: tuple[dict[str, Any], ...] = (
    {"rank": 1, "company": "晶盛机电（300316.SZ）", "process": "长晶、切磨抛与清洗", "customer": "TCL中环半导体级单晶生长设备历史供应关系；Okmetic 12英寸单晶炉交付", "order": "武汉、立昂微合同未公开", "financial": "FY2025集团毛利率28.88%；2026-07-17滚动市盈率（PE-TTM）118.35倍、PB 2.85倍；硅片设备收入未单列", "judgment": "产品覆盖最广，先核验武汉清单；光伏业务会稀释盈利弹性", "refs": ["S028", "S029", "S079", "FIN-JS-01", "FIN-EQ-JINGSHENG-MARKET"]},
    {"rank": 2, "company": "晶升股份（688478.SH）", "process": "12英寸半导体单晶生长", "customer": "上海新昇历史验收；上海新昇、立昂微已形成批量供货", "order": "没有2026—2030新增项目合同", "financial": "Tushare三年序列显示2025年收入1.16亿元、净亏损0.38亿元；PE不适用，单晶炉收入未单列", "judgment": "业务更直接但经营已转亏；只有新增订单、验收和专题收入能确认弹性", "refs": ["S079", "FIN-EQ-JS-ANNUAL", "FIN-EQ-JS-MARKET"]},
    {"rank": 3, "company": "KLA（KLAC.US）", "process": "裸片/外延片缺陷检测与几何量测", "customer": "上海超硅具名合同", "order": "武汉及上海超硅新项目订单未确认", "financial": "FY2025集团毛利率60.91%；2026-07-17滚动市盈率（PE-TTM）60.27倍、PB 47.69倍；裸片检测收入未单列", "judgment": "壁垒和供应证据最强，但对集团收入弹性可能有限", "refs": ["S070", "S034", "S035", "FIN-KLA-01", "FIN-EQ-KLA-MARKET"]},
    {"rank": 4, "company": "Applied Materials（AMAT.US）", "process": "硅外延", "customer": "上海超硅常压外延系统具名合同", "order": "薄层外延新项目未披露采购", "financial": "yfinance四年收入增长，FY2025净利润69.98亿美元；滚动市盈率（PE-TTM）54.06倍，硅外延专用收入未单列", "judgment": "国际平台壁垒强但估值不低；等待新项目合同和专题收入确认传导", "refs": ["S069", "S036", "FIN-EQ-AMAT-ANNUAL", "FIN-EQ-AMAT-MARKET"]},
    {"rank": 5, "company": "PVA TePla（TPE.DE）", "process": "半导体硅晶体生长", "customer": "历史Siltronic具名订单", "order": "FY2025半导体系统订单可见，但无本轮项目映射", "financial": "FY2025半导体系统外部收入1.566亿欧元、分部毛利润0.600亿欧元；披露毛利率37.7%按含内部收入的分部总收入计算。2026-07-17滚动市盈率（PE-TTM）366.40倍、PB 5.58倍", "judgment": "财务穿透较好，项目映射不足；半导体系统仍含非硅片应用", "refs": ["S042", "FIN-PVA-01", "FIN-PVA-02", "FIN-PVA-06", "FIN-PVA-03", "FIN-EQ-PVA-MARKET"]},
    {"rank": 6, "company": "华海清科（688120.SH）", "process": "大硅片CMP、研磨与终洗", "customer": "终洗完成验证并销售，客户未具名", "order": "目标项目合同未公开", "financial": "Tushare三年收入和净利润增长、毛利率由46.02%降至41.81%；滚动市盈率（PE-TTM）139.28倍，硅片专用收入未单列", "judgment": "国产替代空间存在但估值先行；具名客户、终验、复购和专题收入仍是门槛", "refs": ["S031", "S032", "S033", "FIN-EQ-HUHAI-ANNUAL", "FIN-EQ-HUHAI-MARKET"]},
    {"rank": 7, "company": "东京精密（7729.T）", "process": "硅片研磨、边缘成型和脱片清洗", "customer": "公司明确产品用途，无本轮具名项目", "order": "没有直接证据", "financial": "FY2025/03集团毛利率41.49%；2026-07-17滚动市盈率（PE-TTM）28.17倍、PB 3.61倍；硅片专用收入未单列", "judgment": "产品映射清楚，项目份额和收入弹性不足", "refs": ["S050", "FIN-ACC-01", "FIN-EQ-ACCRETECH-MARKET"]},
    {"rank": 8, "company": "北方华创（002371.SZ）", "process": "4—12英寸硅外延", "customer": "产品与累计腔体能力可确认，硅片厂客户未具名", "order": "没有直接证据", "financial": "硅片外延设备收入和毛利未单列", "judgment": "国产化上限较高，需先区分硅衬底与器件晶圆外延", "refs": ["S038", "S039"]},
    {"rank": 9, "company": "中科飞测（688361.SH）", "process": "无图形晶圆缺陷检测", "customer": "产品用途明确，目标硅片厂合同与复购未确认", "order": "没有直接证据", "financial": "硅片专用收入和毛利未单列", "judgment": "替代价值高但当前证据弱，需验证灵敏度、吞吐量与复购", "refs": ["S051", "S052"]},
    {"rank": 10, "company": "ASM International（ASM.AS）", "process": "硅外延", "customer": "年报确认产品能力，目标客户未公开", "order": "没有直接证据", "financial": "硅片外延专用收入和毛利未单列", "judgment": "列入全球竞争者，不列为确定受益", "refs": ["S037"]},
)


LISTED_FINANCIAL_SNAPSHOT_ROWS: tuple[dict[str, Any], ...] = (
    {"company": "晶盛机电（300316.SZ）｜Tushare，2026-07-17", "market_cap": "490.42亿元人民币（约72.46亿美元）", "valuation": "PE 118.35｜PB 2.85｜PS 4.93", "profitability": "ROE 0.60%｜ROA 0.45%", "per_share": "EPS 0.3164元｜BPS 13.15元", "boundary": "指标截至2026-03-31；集团报表受光伏等业务影响，不能替代硅片设备专题收入。", "refs": ["FIN-EQ-JINGSHENG-MARKET"]},
    {"company": "晶升股份（688478.SH）｜Tushare，2026-07-14", "market_cap": "85.16亿元人民币", "valuation": "PE不适用｜PB 5.68｜PS 178.42", "profitability": "ROE -0.58%｜ROA -0.65%", "per_share": "EPS不可得｜BPS 10.83元", "boundary": "指标截至2026-03-31；公司亏损，不能把PE缺失写成0。", "refs": ["FIN-EQ-JS-MARKET"]},
    {"company": "KLA（KLAC）｜yfinance，2026-07-17", "market_cap": "18,808.12亿元人民币（约2,779.10亿美元）", "valuation": "PE 60.27｜PB 47.69｜PS 21.22", "profitability": "ROE 94.98%｜ROA 21.28%", "per_share": "EPS 3.53美元｜BPS 4.46美元", "boundary": "指标截至2026-03-31；人民币市值按同批汇率折算，汇率微差不代表经营变化。", "refs": ["FIN-EQ-KLA-MARKET"]},
    {"company": "Applied Materials（AMAT）｜yfinance，2026-07-14", "market_cap": "32,002.95亿元人民币（约4,729.62亿美元）", "valuation": "PE 54.06｜PB 19.78｜PS接口未返回", "profitability": "ROE 39.69%｜ROA 14.86%", "per_share": "EPS 11.02美元｜BPS 30.11美元", "boundary": "综合前道设备集团；估值不能替代硅外延专题订单与利润。", "refs": ["FIN-EQ-AMAT-MARKET"]},
    {"company": "PVA TePla（TPE.DE）｜yfinance，2026-07-17", "market_cap": "57.82亿元人民币（约8.54亿美元）", "valuation": "PE 366.40｜PB 5.58｜PS 3.11", "profitability": "ROE 1.40%｜ROA 1.66%", "per_share": "EPS 0.10欧元｜BPS 6.57欧元", "boundary": "指标截至2026-03-31；半导体系统仍包含硅片长晶以外应用。", "refs": ["FIN-EQ-PVA-MARKET"]},
    {"company": "华海清科（688120.SH）｜Tushare，2026-07-14", "market_cap": "1,528.72亿元人民币", "valuation": "PE 139.28｜PB 19.80｜PS 30.96", "profitability": "ROE 3.26%｜ROA 2.21%", "per_share": "EPS 2.2186元｜除权同口径BPS 15.60元", "boundary": "原始2026-03-31 BPS为21.83元，按0.39892流通股份变动比例换算；综合设备财务不能替代大硅片CMP、研磨和终洗专题收入。", "refs": ["FIN-EQ-HUHAI-MARKET", "FIN-EQ-HUHAI-DIVIDEND"]},
    {"company": "东京精密（7729.T）｜yfinance，2026-07-17", "market_cap": "287.83亿元人民币（约42.53亿美元）", "valuation": "PE 28.17｜PB 3.61｜PS 4.15", "profitability": "ROE 13.45%｜ROA 8.63%", "per_share": "EPS 605.45日元｜BPS 4,723.02日元", "boundary": "指标截至2026-03-31；综合半导体设备财务不能替代硅片专用收入。", "refs": ["FIN-EQ-ACCRETECH-MARKET"]},
)


ENTITY_UNIQUE_ANALYSIS: dict[str, str] = {
    "semiconductor_crystal_growth_tools": """
### 为什么本环节不能直接估算炉台数

单晶炉台数由晶体直径、晶锭有效长度、单炉周期、拉速、成晶率、良率、热场寿命、检修时间和备机率共同决定。武汉项目只披露设计月产能和设备搬入时间，没有公开这些参数；Linton产品页虽列出热场直径和拉速，也不足以把拉速直接换成合格硅片月产量。^src:source_ref:S011 ^src:source_ref:S040 因此，本页只用已投产完整线的生产设备投入校准金额，不写“需要多少台单晶炉”。这比用行业经验硬填台数更保守，也避免把晶锭加工、厂务和自动化重复计入长晶设备。

### 300毫米、200毫米与海外项目的差异

300毫米高规格硅片对热场稳定性、氧碳含量、晶体缺陷和自动化要求更高，武汉完整线与SUMCO晶体项目是本轮主要新增观察对象；200毫米市场更多依赖成熟设备、改造和多品类切换，不能沿用武汉投资强度。SUMCO修订后在2028年和2030年启动部分晶体能力，而主要晶圆加工能力延后到2031年，说明长晶设备与完整硅片线的采购时点并不相同。^src:source_ref:S014 SK Siltron与环球晶圆已经投入的大额项目则处于爬坡阶段，未来需求更可能来自瓶颈、备机和后续阶段，历史总投资不能再次计入。^src:source_ref:S018 ^src:source_ref:S023

### 供应商差异和收入验证

晶盛机电覆盖单晶炉及后续多道设备，并披露向Okmetic交付12英寸半导体单晶炉；晶升股份有上海新昇历史验收以及上海新昇、立昂微批量供货；PVA TePla既有半导体晶圆用长晶系统产品，也有Siltronic历史订单。^src:source_ref:S029 ^src:source_ref:S079 ^src:source_ref:S042 ^src:source_ref:FIN-PVA-02 但三家公司都没有公开武汉项目合同。晶盛机电的合并报表受光伏业务影响，PVA TePla半导体系统还包含硅片长晶以外应用；订单若不具名，就无法确认本主题对集团收入的增量。

本环节最重要的领先指标不是公司展示产品，而是项目设备清单、单晶炉招标、首批搬入和分阶段验收。若同一供应商出现连续复购、设备稳定量产并在专题订单或分部收入中得到验证，才可以从“具备能力”推进到“正在受益”。反之，硅片厂提高既有炉台利用率、推迟热场采购或延长验收，都会显著削弱新增订单。
""".strip(),
    "wafer_grinding_polishing_tools": """
### 为什么研磨和抛光必须分设备、分验收看

硅锭切片后要经过倒角、研磨、腐蚀、双面抛光和最终抛光，不同设备分别控制厚度、平坦度、边缘形貌、表面粗糙度与缺陷。上海超硅把抛光列为现有瓶颈，披露向SpeedFam、Lapmaster Wolters采购双面抛光设备，并确认与Okamoto等终端生产商建立直接采购或合作渠道；公开资料没有披露Okamoto对应的具体机型和本轮项目合同。西安奕材则披露国产CMP已经转固，而减薄研磨设备尚未完成最终验收。^src:source_ref:S067 ^src:source_ref:S071 ^src:source_ref:S081 ^src:source_ref:S075 ^src:source_ref:S076 这组对照说明，设备已经采购、已经付款、已经转固和已经通过最终验收是四个不同阶段，不能用一条“国产化”标签概括。

### 台数示例为什么不进入正式项目预测

西安奕材材料可用于复核特定型号的名义产能和采购数量，但武汉项目没有公开相同型号、设备综合效率、备机率和目标良率。不同硅片规格的加工次数也不相同：300毫米先进逻辑用硅片对纳米级平坦度和边缘形貌要求更严，功率外延衬底与SOI顶层硅又增加专门减薄和表面恢复。因此，即使目标月产能相同，台数和价值量也可能明显不同。本页只把公开单机数据作为数量级检查，不把它搬到武汉形成伪精确采购清单。

### 国内外竞争如何比较

东京精密明确区分硅片制造设备与芯片前后道设备，产品包含研磨抛光、边缘成型和切片后脱片清洗；华海清科明确覆盖大硅片CMP、研磨和终洗，浙江芯晖装备又有西安奕材具名采购。招股书释义和法人表明确，西安芯晖设备（原西安奕斯伟设备）对应12英寸拉晶设备，不能与前述研磨/CMP主体混写。^src:source_ref:S050 ^src:source_ref:S031 ^src:source_ref:S032 ^src:source_ref:S075 ^src:source_ref:S076 ^src:source_ref:S077 ^src:source_ref:S064 DISCO本轮核验产品最高支持8英寸，不能外推为武汉12英寸整线；Ebara边缘抛光产品用途同时包含器件晶圆薄膜去除，也不能在缺客户时写成硅片项目供应。^src:source_ref:S043 ^src:source_ref:S044

因此，本环节的国产替代空间真实存在，但排序首先取决于最终验收、复购、平坦度和颗粒指标，其次才是产品目录。东京精密和华海清科的集团或综合财务均没有单列硅片研磨抛光收入，不能用集团毛利率估项目利润。下一步最能改变结论的信息是武汉设备品牌与数量、国产设备终验、连续复购、单机有效节拍和停机率。
""".strip(),
    "silicon_epitaxy_tools": """
### 外延为什么不能套普通抛光片整线参数

外延片是在抛光衬底上生长受控单晶层，价值来自反应腔、气体输送、温度场、厚度均匀性和缺陷控制。上海超硅300毫米薄层外延项目直接披露设备及安装预算27.86亿元，立昂微又分别披露重掺衬底、轻掺和其他外延项目；这些专线的产品、工艺和设备配置与武汉普通300毫米完整抛光片线不同。^src:source_ref:S068 ^src:source_ref:S073 ^src:source_ref:S074 因此，外延项目优先使用自身预算，绝不套用每新增1万片/月1.12—1.36亿元的完整线参数。

### 当前可计算到哪里

上海超硅项目尚处募投规划阶段，建设期24个月但开工日未披露；立昂微180万片/年外延项目截至2025年末工程进度20.60%，预定可使用时间延至2027年底。工程进度不是设备采购进度，剩余总预算也不等于剩余设备额。本模型只把立昂微未完成预算乘上海超硅可比设备占比形成零至上限的敏感性，并把上海超硅预算只放入条件上限；不再平滑分配到每个年度，也没有选择一个没有校准的中心比例。

### 谁真正具有直接证据

应用材料与上海超硅存在常压外延系统具名合同，产品页也确认200毫米量产硅外延平台；ASM年报与北方华创产品页证明各自具备硅外延设备能力。^src:source_ref:S069 ^src:source_ref:S036 ^src:source_ref:S037 ^src:source_ref:S038 ^src:source_ref:S039 但ASM和北方华创缺少本轮硅片厂具名客户，晶盛机电虽然披露半导体设备产品链，也没有新外延项目合同。产品能力回答“能否参与”，具名合同才回答“是否已经参与”，两者不能放在同一证据等级。

功率与汽车需求提高重掺衬底和外延价值，先进逻辑也可能增加特定外延或退火规格，但客户认证决定实际品类。设备收入还受到融资、开工、腔体交付、安装、初验、终验与服务合同影响。若上海超硅融资和开工继续后移，或立昂微优先消化已有设备，本环节的2026—2030设备需求会显著低于规划预算。需要补充反应腔数量、厚度均匀性和缺陷指标、具名合同与收入确认条款后，才能估算供应商盈利弹性。
""".strip(),
    "bare_wafer_metrology_tools": """
### 为什么检测价值随硅片规格上升

裸硅片和外延片的出厂控制至少包括表面颗粒与缺陷、纳米形貌、厚度、平坦度、翘曲和边缘区域。先进逻辑、存储和薄层外延把缺陷灵敏度、重复性与数据库一致性要求推高，因此检测设备的价值并不只随片数变化，也随产品规格和客户认证提高。上海超硅披露多份KLA表面缺陷与几何量测合同，KLA监管材料又明确Surfscan、WaferSight等用于晶圆和衬底质量控制，这构成本轮最直接的国际供应证据。^src:source_ref:S070 ^src:source_ref:S034 ^src:source_ref:S035

### 国产候选为什么仍在观察层

中科飞测监管文件和当前产品目录证明无图形晶圆缺陷检测可以用于硅片出厂品质管控，并给出灵敏度与吞吐参数。^src:source_ref:S051 ^src:source_ref:S052 但目标硅片厂、当前产品代际、复购和长期稼动率没有公开；精测电子本轮又没有找到硅衬底制造产品和具名客户的一手证据。因此，国产替代不能只看“量检测设备”标签，而要比较实际灵敏度、吞吐量、重复性、误报率、设备数据库、服务响应和客户量产记录。

### 市场金额和公司收入为何仍不能量化

武汉、立昂微和上海超硅新项目都没有公开检测设备数量、单价和供应商份额，完整线预算也没有按工序拆分。本页只能先确认每条产线需要检测、并按产品规格筛选厂商；没有工序价值占比时，不给KLA或国产公司分配项目金额。KLA FY2025集团毛利率60.91%来自广泛制程控制组合，不能作为裸片检测项目毛利率，也不能乘中国项目池推净利润。^src:source_ref:FIN-KLA-01

本环节最强的上行证据将是新项目具名合同、同一客户复购和更高规格产品量产；最强的反方则是客户沿用既有进口检测平台，只在瓶颈处少量加机，或国产设备未达到灵敏度与重复性要求。若要推进研究，需要补武汉检测清单、KLA当前机型与单价、国产产品量产验收、复购和服务合同，并把订单与分部收入、经营现金流对上。
""".strip(),
    "wafer_final_clean_automation": """
### 为什么终洗与自动化是必需工序却不一定高弹性

硅片在研磨、抛光或SOI剥离后必须去除颗粒、金属污染和化学残留，自动上下料与厂内传输还决定整线节拍和人为污染风险。因此，完整新线一定需要终洗与自动化，但金额可能由整线集成商打包，也可能沿用客户既有平台；项目总投资不能按平均比例分配。本轮项目资料没有公开武汉终洗、搬运或仓储自动化的品牌、台数与金额，所以这一环节的公开证据弱于长晶、抛光和检测。

### 当前直接证据能支持什么

华海清科披露HSC-F3400大硅片终洗设备已完成验证并实现销售，但没有具名客户；东京精密综合报告明确列出用于硅片制造的切片后脱片清洗设备；晶盛机电产品链也覆盖清洗与自动化。^src:source_ref:S033 ^src:source_ref:S050 ^src:source_ref:S028 这些证据足以证明产品存在和部分验证，不足以证明武汉、立昂微或上海超硅新项目已经采购。芯源微KS-CM300服务沉积、刻蚀、离子注入、CMP和去胶后的器件晶圆清洗，不能因为名称相似就当作硅衬底终洗。^src:source_ref:S053

### 200毫米、300毫米和SOI的差异

300毫米完整线更依赖高洁净自动上下料、载具和厂内接口，颗粒控制及设备间节拍匹配要求高；200毫米成熟产线可能通过改造或局部加机扩产；SOI还要清除离子注入剥离、减薄和再抛光残留，并保护键合界面。^src:source_ref:S004 因此，普通单片清洗、脱片清洗、最终清洗和整线自动化不能合并成同一个市场，也不能用一台设备的验证覆盖整条链。

华海清科和东京精密的集团业务均包含远超终洗与自动化的产品组合，专题收入和毛利没有单列；产品销售也可能只是少量单机。只有具名客户、复购、颗粒指标、整线接口验收、合同负债与收入确认能够相互印证，才能判断盈利弹性。若客户由海外整线商打包、国产设备只完成试用而未复购，或新线采购后移，本环节会维持低可见度。需要补武汉厂内物流与终洗清单、设备综合效率、颗粒与金属污染指标、连续复购和验收周期。
""".strip(),
}


ENTITY_PROJECT_TO_FINANCIAL_BRIDGE: dict[str, str] = {
    "semiconductor_crystal_growth_tools": (
        "长晶设备的金额首先取决于拉晶炉台数、单炉有效产能、热场寿命和备机安排，而不是整线投资的固定比例。"
        "西安奕材与上海新昇的历史交付证明晶升股份、西安芯晖设备等厂商曾进入12英寸体系，但武汉项目的炉型、"
        "台数、磁场配置和品牌仍未公开。对上市公司而言，还要区分单晶炉整机、热场耗材、安装服务和验收节点；"
        "晶盛机电集团收入包含光伏与其他设备，晶升股份2025年又出现收入下滑和亏损。只有武汉具名合同、交付批次、"
        "终验以及半导体单晶炉收入和现金回款能够相互核对，才可把项目条件金额转成公司盈利。"
    ),
    "wafer_grinding_polishing_tools": (
        "研磨与抛光的台数不能只用名义月处理能力相除。设备综合效率、产品切换、返工、备机和最终抛光道次都会改变"
        "有效产能。本页需要的输入是目标月产能、单台名义月能力、设备综合效率、返工比例、道次、备机率和可核验单价；"
        "输入齐全时，先按‘目标有效月产能÷（单台名义月能力×设备综合效率）×（1+备机率）’估台数，再乘具名合同单价估金额。"
        "当前设备综合效率、返工、备机和武汉机型均未披露，所以只展示计算方法，不输出项目台数或金额。西安奕材的实际案例显示，CMP设备转固并不等于全部最终验收，而研磨减薄设备在高比例付款后仍因"
        "光滑度参数稳定性没有验收；这使国产化率和收入确认必须按设备逐台分层。东京精密、SpeedFam、Lapmaster"
        "具有直接产品证据；上海超硅与Okamoto的采购渠道或合作关系可确认，但具体机型和本轮合同未披露。"
        "浙江芯晖装备具有具名客户，但武汉项目品牌与台数均未披露。公司盈利分析"
        "需补合同金额、验收状态、保修与复购，并把硅片专用设备收入从集团CMP或其他研磨业务中拆出。"
    ),
    "silicon_epitaxy_tools": (
        "外延项目最接近直接预算口径：上海超硅披露27.856575亿元设备及安装费，但该金额覆盖整条外延项目设备，"
        "不能全部归给外延反应腔，也不能全部归给Applied Materials。立昂微项目因延期且已采购部分不明，只能在四项目"
        "高情景中用剩余预算作代理。外延设备收入还要经过融资、开工、腔体合同、安装、工艺调试和终验；每一步都可能"
        "跨财年。应用材料的集团收入和高估值来自广泛前道设备组合，北方华创与ASM的产品页也只证明能力。若没有具名"
        "腔体数量、单价和验收，报告不为任何厂商分配规划预算。"
    ),
    "bare_wafer_metrology_tools": (
        "裸片检测的价值随缺陷灵敏度、吞吐、重复性和数据库兼容性变化，不能用晶圆片数乘统一单价。上海超硅与KLA的"
        "历史合同确认了Surfscan和几何量测平台的客户关系，但武汉与立昂微新增线是否沿用同一平台、是否增加边缘或"
        "SOI专用量测均未公开。国产候选还需证明在目标规格下连续量产、复购和服务响应，而不是只达到实验室灵敏度。"
        "KLA集团毛利率覆盖制程控制全产品线，中科飞测等公司的收入也包含器件晶圆量检测；只有新项目合同、机型、台数、"
        "验收与裸片专题收入，才能判断设备需求是否对公司利润产生可见弹性。"
    ),
    "wafer_final_clean_automation": (
        "终洗和自动化是完整线必需环节，但单项金额可能较小，也可能被整线集成商打包，因此不能从项目总预算平均切分。"
        "本页的必要输入包括每道清洗的目标节拍、设备综合效率、颗粒与金属污染指标、自动上下料接口、备机率、单机价格和"
        "是否被整线打包；若这些输入齐全，台数按‘目标月产能÷（单机有效月处理量）×（1+备机率）’计算，金额再乘可核验单价。"
        "武汉项目没有披露上述输入，华海清科也没有披露目标客户单价，因此本轮明确不作金额估算。"
        "华海清科披露大硅片终洗设备完成验证并销售，东京精密披露切片后脱片清洗产品，晶盛机电也覆盖清洗与自动化；"
        "这些材料仍没有给出武汉项目具名采购。不同尺寸、颗粒与金属污染指标、载具接口和上下料节拍会改变设备配置，"
        "200毫米改造线也可能只局部加机。华海清科三年收入增长但毛利率回落，且终洗专题收入未单列，所以必须取得客户、"
        "复购、整线接口验收、合同金额和回款，才能判断增长是否由硅片终洗贡献。"
    ),
}


ENTITY_CONCLUSIONS: dict[str, str] = {
    "semiconductor_crystal_growth_tools": (
        "根据现有证据，可以认为半导体单晶生长设备在2026—2030年存在新增需求，但订单节奏取决于项目实际搬入。"
        "武汉项目计划在2026年四季度搬入设备，SUMCO修订后的晶体产能则分到2028年和2030年启动；晶盛机电、"
        "晶升股份和PVA TePla的历史交付证明它们具备参与能力，却不能证明已取得武汉或SUMCO的新订单。"
        "当前缺少武汉单晶炉品牌、炉台数、价格和验收安排，因此对行业需求的判断强于对单家公司收入的判断。"
        "如果搬入继续后移、客户优先提高现有炉台利用率，或国产炉的稳定性与热场寿命未通过验收，预期订单会明显下调。"
        "现阶段最可靠的结论是把具名招标、首批搬入和最终验收作为确认点，而不是先给供应商分配项目金额。"
    ),
    "wafer_grinding_polishing_tools": (
        "根据现有证据，可以较有把握地认为研磨与抛光是完整硅片线的真实瓶颈，但国产替代成熟度在同一客户内也明显分化。"
        "上海超硅披露的瓶颈能力和采购单价说明产能扩张会带来设备需求；西安奕材的5台国产CMP已经转固，"
        "其中2台仍未完成最终验收，而3台研磨减薄设备在支付90%价款后仍因稳定性不足未验收。"
        "这意味着2026—2030年的机会不能用一个国产化率概括，也不能把付款或转固直接当作设备商收入完全兑现。"
        "武汉和立昂微尚未公开机型、设备综合效率、返工率与备机配置，因而目前无法可靠计算台数或供应商份额。"
        "只有同规格设备的最终验收、连续量产和复购同时出现，才能确认国产设备从导入走向批量替代。"
    ),
    "silicon_epitaxy_tools": (
        "根据现有证据，可以认为硅外延设备是本轮金额较清楚、时间却仍有较大不确定性的环节。"
        "上海超硅薄层外延项目直接披露27.86亿元设备及安装预算，应用材料又有历史具名合同；"
        "立昂微180万片项目工程进度仅20.60%，并因既有产能利用不足把预定可使用时间延至2027年12月。"
        "因此，规划预算支持中期需求判断，却不能证明资金、腔体合同或当期收入已经落地。"
        "如果融资或开工继续推迟、客户先消化现有外延能力，或新平台未达到厚度均匀性与缺陷要求，实际采购会低于预算。"
        "当前可作中等把握的条件判断：项目开工、具名腔体合同和安装验收连续出现后，外延设备才会成为可见收入。"
    ),
    "bare_wafer_metrology_tools": (
        "根据现有证据，可以认为高规格裸硅片与外延片会提高缺陷检测和几何量测要求，而且供应壁垒高于一般产品匹配。"
        "上海超硅与KLA的历史合同证明KLA曾进入硅片制造环节，中科飞测的材料也证明国产无图形检测具备产品基础；"
        "但武汉、立昂微和上海超硅新项目都没有公开检测设备数量、当前机型、单价或复购结果。"
        "因此，工序必要性和KLA的历史竞争位置较清楚，新项目收入和国产替代份额仍无法根据公开资料推断。"
        "若客户沿用既有进口平台，只在局部瓶颈加机，或国产设备未达到灵敏度、重复性与长期稼动率要求，"
        "新增需求对供应商盈利的影响会很小；具名合同、同客户复购和量产质量记录是下一步的确认条件。"
    ),
    "wafer_final_clean_automation": (
        "根据现有证据，可以认为终洗与自动化是新建完整线不可缺少的工序，但它目前是五个环节中订单可见度最低的一类。"
        "华海清科已披露大硅片终洗设备完成验证并销售，东京精密和晶盛机电也有对应产品；"
        "公开资料却没有把这些产品映射到武汉或立昂微的品牌、台数、整线接口和验收。"
        "该环节还可能由整线集成商打包，200毫米改造线也可能沿用原有平台，所以不能从完整线预算平均切分市场金额。"
        "如果产品长期停留在匿名单机销售、没有复购和颗粒指标，或客户继续使用既有自动化系统，盈利贡献将低于工序必要性所暗示的水平。"
        "现阶段只能确认产品与早期验证，具名客户、整线接口验收、复购和专题收入出现后才能提高判断把握。"
    ),
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_final_data_point_audit(
    data_points: Sequence[Mapping[str, Any]],
    *,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    output_dir: Path,
) -> tuple[dict[str, Any], str]:
    """Audit every final post-supplement data point against the source catalog."""
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, point in enumerate(data_points, start=1):
        ref = str(point.get("source_ref") or "")
        source = sources_by_ref.get(ref)
        title = str(point.get("data_point_title") or f"数据点{index}")
        checks = {
            "source_exists": source is not None,
            "source_excerpt_present": bool(str(point.get("source_excerpt") or "").strip()),
            "metric_present": bool(str(point.get("metric") or "").strip()),
            "period_present": bool(str(point.get("period") or "").strip()),
            "interpretation_present": bool(str(point.get("interpretation") or "").strip()),
            "translated_excerpt_present_if_needed": (
                True
                if not source
                or str(source.get("language") or "zh-CN").lower().startswith("zh")
                else bool(str(point.get("source_excerpt_zh") or "").strip())
            ),
        }
        status = "pass" if all(checks.values()) else "fail"
        if status == "fail":
            failures.append(title)
        results.append(
            {
                "data_point_index": index,
                "data_point_title": title,
                "source_ref": ref,
                "source_title": (
                    str(source.get("title_zh") or source.get("title") or "")
                    if source
                    else ""
                ),
                "checks": checks,
                "status": status,
            }
        )
    payload: dict[str, Any] = {
        "audit_version": "equipment.final_data_points.v1",
        "as_of_date": AS_OF_DATE,
        "audited_data_point_count": len(results),
        "itemized_result_count": len(results),
        "coverage_complete": len(results) == len(data_points),
        "failure_count": len(failures),
        "failed_data_point_titles": failures,
        "data_point_set_sha256": _sha256_json(list(data_points)),
        "source_catalog_sha256": _sha256_json(list(sources_by_ref.values())),
        "results": results,
    }
    path = output_dir / "final_data_point_evidence_audit.json"
    write_json(path, payload)
    return payload, sha256_file(path)


_GENERIC_SOURCE_LOCATORS = {
    "",
    "原始网页或PDF所列段落",
    "原始网页所列段落",
    "原始PDF所列段落",
}


def _collect_source_refs(value: Any, *, known_refs: set[str]) -> set[str]:
    refs: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for child in item.values():
                visit(child)
            return
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child)
            return
        if not isinstance(item, str):
            return
        text = item.strip()
        if text in known_refs:
            refs.add(text)
        for ref in re.findall(r"source_ref:([A-Za-z0-9_.-]+)", text):
            if ref in known_refs:
                refs.add(ref)

    visit(value)
    return refs


def _build_source_traceability_audit(
    *,
    pack: Mapping[str, Any],
    model_inputs: Mapping[str, Any],
    direct_excerpt_audit: Mapping[str, Any],
) -> dict[str, Any]:
    source_by_ref = {
        str(source["ref"]): source
        for source in pack.get("sources") or []
    }
    known_refs = set(source_by_ref)

    def is_precise(source: Mapping[str, Any]) -> bool:
        locator = str(source.get("local_locator") or "").strip()
        return bool(locator) and locator not in _GENERIC_SOURCE_LOCATORS and not locator.startswith(
            "原始网页或PDF所列"
        )

    def is_identity_complete(source: Mapping[str, Any]) -> bool:
        core_complete = all(
            str(source.get(field) or "").strip()
            for field in ("title", "publisher", "excerpt")
        )
        has_retrieval_identity = bool(
            str(source.get("url") or "").strip()
            or str(source.get("local_path") or "").strip()
        )
        return core_complete and has_retrieval_identity

    public_refs = _collect_source_refs(
        {
            "sections": pack.get("sections") or [],
            "entity_sections": pack.get("entity_sections") or [],
            "targets": pack.get("entity_investment_targets") or [],
            "visuals": pack.get("visuals") or [],
            "claims": pack.get("claims") or [],
            "supplement_requests": pack.get("supplement_requests") or [],
        },
        known_refs=known_refs,
    )
    core_table_refs = _collect_source_refs(
        pack.get("visuals") or [],
        known_refs=known_refs,
    )
    model_input_refs = _collect_source_refs(model_inputs, known_refs=known_refs)
    usable_slots = [
        slot
        for entity in pack.get("entities") or []
        for factor in entity.get("factor_scores") or []
        for slot in factor.get("metric_slots") or []
        if str(slot.get("value_status") or "")
        in {"available", "calculated", "stale_but_usable"}
    ]
    usable_slot_refs = _collect_source_refs(usable_slots, known_refs=known_refs)

    def coverage(refs: set[str]) -> dict[str, Any]:
        generic_refs = sorted(ref for ref in refs if not is_precise(source_by_ref[ref]))
        incomplete_identity_refs = sorted(
            ref for ref in refs if not is_identity_complete(source_by_ref[ref])
        )
        return {
            "source_ref_count": len(refs),
            "precise_locator_count": len(refs) - len(generic_refs),
            "generic_locator_count": len(generic_refs),
            "generic_locator_refs": generic_refs,
            "identity_complete_count": len(refs) - len(incomplete_identity_refs),
            "identity_incomplete_count": len(incomplete_identity_refs),
            "identity_incomplete_refs": incomplete_identity_refs,
        }

    all_source_refs = set(source_by_ref)
    all_source_coverage = coverage(all_source_refs)
    public_coverage = coverage(public_refs)
    core_table_coverage = coverage(core_table_refs)
    model_input_coverage = coverage(model_input_refs)
    usable_slot_coverage = coverage(usable_slot_refs)
    high_impact_refs = public_refs | core_table_refs | model_input_refs | usable_slot_refs
    downgraded_refs = sorted(
        ref
        for ref in high_impact_refs
        if not is_precise(source_by_ref[ref]) or not is_identity_complete(source_by_ref[ref])
    )
    audit = {
        "audit_version": "equipment.source_traceability.v1",
        "as_of_date": AS_OF_DATE,
        "source_catalog_sha256": _sha256_json(list(pack.get("sources") or [])),
        "model_inputs_sha256": _sha256_json(model_inputs),
        "all_sources": all_source_coverage,
        "public_body_and_targets": public_coverage,
        "core_tables": core_table_coverage,
        "model_inputs": model_input_coverage,
        "usable_metric_slots": {
            **usable_slot_coverage,
            "usable_slot_count": len(usable_slots),
        },
        "downgraded_due_to_traceability_count": len(downgraded_refs),
        "downgraded_due_to_traceability_refs": downgraded_refs,
        "direct_original_excerpt_count": int(
            direct_excerpt_audit.get("direct_original_excerpt_count") or 0
        ),
        "summary_rewrite_count": int(
            direct_excerpt_audit.get("summary_rewrite_count") or 0
        ),
        "EQ-EVID-005": str(direct_excerpt_audit.get("EQ-EVID-005") or "open"),
        "status": (
            "pass"
            if not downgraded_refs
            and not all_source_coverage["generic_locator_count"]
            and direct_excerpt_audit.get("status") == "pass"
            else "fail"
        ),
        "boundary": (
            "该审计检查来源身份字段、定位是否具体，以及公开正文、核心表、模型输入和可用指标槽是否都能回到来源；"
            "它不以字符串检查替代独立reviewer对摘录忠实度和结论强度的人工核验。"
        ),
    }
    if audit["status"] != "pass":
        raise ValueError(f"设备来源可追溯性审计失败：{audit}")
    return audit


def _source_catalog(
    equipment_sources: Sequence[Mapping[str, Any]] | None = None,
    *,
    financial_targets_payload: Mapping[str, Any] | None = None,
    financial_sources_payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    equipment_payload = _load_json(EQUIPMENT_DIR / "sources.json")
    raw_equipment_sources = list(equipment_sources) if equipment_sources is not None else equipment_payload["sources"]
    sources = [
        normalize_agent_source(source, local_path_map=LOCAL_PATH_MAP, fetch_date=AS_OF_DATE)
        for source in raw_equipment_sources
        if source.get("source_id") != "S002"
    ]
    demand_source_rows = {
        str(source["source_id"]): source
        for source in _load_json(DEMAND_DIR / "sources.json")["sources"]
    }
    for original_ref, equipment_ref in DEMAND_DRIVER_SOURCE_REF_MAP.items():
        if original_ref not in demand_source_rows:
            raise ValueError(f"设备侧需求传导来源缺失：{original_ref}")
        source = dict(demand_source_rows[original_ref])
        source["source_id"] = equipment_ref
        source["local_locator"] = DEMAND_DRIVER_SOURCE_LOCATORS[equipment_ref]
        sources.append(normalize_agent_source(source, fetch_date=AS_OF_DATE))
    target_payload = financial_targets_payload or _load_json(FINANCIAL_TARGETS_PATH)
    equipment_target_ids = {"jingsheng", "accretech", "pva_tepla", "kla"}
    wanted: set[str] = set()
    for target in target_payload["targets"]:
        if target["target_id"] not in equipment_target_ids:
            continue
        wanted.add(str(target["ticker_verification"]["source_ref"]))
        for row in target.get("financials") or []:
            wanted.add(str(row["source_ref"]))
            wanted.update(
                str(item["source_ref"])
                for item in row.get("field_evidence") or []
            )
        for point in target.get("target_data_points") or []:
            wanted.add(str(point["evidence_ref_uri"]).replace("source_ref:", ""))
        for item in target.get("recent_evidence") or []:
            wanted.update(str(ref) for ref in item.get("source_refs") or [])
        if target.get("segment_snapshot", {}).get("source_ref"):
            wanted.add(str(target["segment_snapshot"]["source_ref"]))
    financial_payload = financial_sources_payload or _load_json(FINANCIAL_SOURCES_PATH)
    for source in financial_payload["sources"]:
        if source["ref"] in wanted:
            sources.append(normalize_agent_source(source, fetch_date=AS_OF_DATE))
    for source in supplemental_financial_source_rows():
        sources.append(
            normalize_agent_source(
                _humanize_public_aliases(source),
                fetch_date=AS_OF_DATE,
            )
        )
    sources.append(normalize_agent_source(LEGAL_ENTITY_SOURCE, fetch_date=AS_OF_DATE))
    sources.append(normalize_agent_source(HISTORICAL_CYCLE_SOURCE, fetch_date=AS_OF_DATE))
    sources.extend(
        normalize_agent_source(source, local_path_map=LOCAL_PATH_MAP, fetch_date=AS_OF_DATE)
        for source in CRITICAL_FACT_CLUSTER_SOURCES
    )
    # 同一底层文件或产品材料跨设备/财务代理重复出现时只计一个证据组。
    # ref 继续保留，以免破坏既有数据点与标的引用。
    duplicate_groups = {
        "S034": "issuer:kla:surfscan_sp7_product_family",
        "FIN-KLA-02": "issuer:kla:surfscan_sp7_product_family",
        "S050": "issuer:accretech:integrated_report_2025",
        "FIN-ACC-03": "issuer:accretech:integrated_report_2025",
        "S042": "issuer:pva_tepla:annual_report_2023",
        "FIN-PVA-03": "issuer:pva_tepla:annual_report_2023",
    }
    duplicate_rationale = {
        "issuer:kla:surfscan_sp7_product_family": "KLA Surfscan SP7同一产品族材料合并计为一个证据组。",
        "issuer:accretech:integrated_report_2025": "东京精密2025综合报告在设备与财务代理中重复出现，合并计为一个证据组。",
        "issuer:pva_tepla:annual_report_2023": "PVA TePla 2023年报在设备与财务代理中重复出现，合并计为一个证据组。",
    }
    duplicate_date_overrides = {
        "S034": "2018-07-10",
        "FIN-KLA-02": "2018-07-10",
        "S050": "2025",
        "FIN-ACC-03": "2025",
        "S042": "2024",
        "FIN-PVA-03": "2024",
    }
    for source in sources:
        ref = str(source["ref"])
        if ref in duplicate_groups:
            source["independence_key"] = duplicate_groups[ref]
            source["independence_rationale"] = duplicate_rationale[duplicate_groups[ref]]
            source["publish_date"] = duplicate_date_overrides[ref]
            source["event_date"] = duplicate_date_overrides[ref]
            if duplicate_date_overrides[ref].startswith(("2018", "2024")):
                source["source_review_status"] = "stale"
                source["staleness_warning"] = (
                    "该资料只证明历史产品能力或报告期事实，不能单独证明2026—2030年的新增订单。"
                )
        if ref in FINANCIAL_SOURCE_OVERRIDES:
            source.update(FINANCIAL_SOURCE_OVERRIDES[ref])
        for public_metadata_field in (
            "local_locator",
            "independence_rationale",
            "staleness_warning",
        ):
            if source.get(public_metadata_field):
                source[public_metadata_field] = _humanize_public_aliases(
                    source[public_metadata_field]
                )
    refs = [source["ref"] for source in sources]
    if len(refs) != len(set(refs)):
        raise ValueError("设备侧来源 ref 重复")
    return sources


def _source_excerpt_similarity(left: str, right: str) -> float:
    compact_left = re.sub(r"\s+", "", left).lower()
    compact_right = re.sub(r"\s+", "", right).lower()
    if not compact_left or not compact_right:
        return 0.0
    return SequenceMatcher(None, compact_left, compact_right).ratio()


def _apply_direct_source_excerpts(
    sources: list[dict[str, Any]],
    data_points: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind every source to an original excerpt or an exact structured record.

    Data-point-backed sources use the exact source_excerpt already accepted by
    the itemized evidence audit. Sources without a data point must be listed in
    an explicit direct-source registry; an unclassified source hard-fails the
    build instead of silently preserving a researcher-written summary.
    """

    points_by_ref: dict[str, list[Mapping[str, Any]]] = {}
    for point in data_points:
        points_by_ref.setdefault(str(point.get("source_ref") or ""), []).append(point)

    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for source in sources:
        ref = str(source["ref"])
        old_excerpt = str(source.get("excerpt") or "")
        points = points_by_ref.get(ref) or []
        if ref in CRITICAL_FACT_CLUSTER_REFS:
            exact_excerpt = str(source.get("excerpt") or "").strip()
            origin_kind = "verified_regulatory_fact_cluster_quote"
            origin_detail = str(source.get("local_locator") or "")
        elif points:
            selected = max(
                points,
                key=lambda point: (
                    _source_excerpt_similarity(
                        old_excerpt,
                        str(point.get("source_excerpt") or ""),
                    ),
                    len(str(point.get("source_excerpt") or "")),
                ),
            )
            exact_excerpt = str(selected.get("source_excerpt") or "").strip()
            translated = str(selected.get("source_excerpt_zh") or "").strip()
            if not exact_excerpt:
                failures.append({"ref": ref, "reason": "audited_data_point_missing_excerpt"})
                continue
            source["excerpt"] = exact_excerpt
            if translated:
                source["excerpt_zh"] = translated
            elif str(source.get("language") or "").lower().startswith("zh"):
                source["excerpt_zh"] = exact_excerpt
            origin_kind = "audited_data_point_exact"
            origin_detail = str(selected.get("data_point_key") or "")
        elif ref in DIRECT_SOURCE_EXCERPT_OVERRIDES:
            override = DIRECT_SOURCE_EXCERPT_OVERRIDES[ref]
            source.update(override)
            exact_excerpt = str(source.get("excerpt") or "").strip()
            origin_kind = "verified_original_source_quote"
            origin_detail = str(source.get("local_locator") or "")
        elif ref == "FIN-EQ-HUHAI-DIVIDEND":
            exact_excerpt = str(source.get("excerpt") or "").strip()
            origin_kind = "verified_regulatory_source_quote"
            origin_detail = str(source.get("local_locator") or "")
        elif ref.startswith("FIN-EQ-"):
            exact_excerpt = str(source.get("excerpt") or "").strip()
            origin_kind = "frozen_structured_provider_record"
            origin_detail = str(source.get("local_locator") or "")
        elif ref in DIRECT_FINANCIAL_TABLE_REFS:
            exact_excerpt = str(source.get("excerpt") or "").strip()
            origin_kind = "financial_table_transcription"
            origin_detail = str(source.get("local_locator") or "")
        else:
            failures.append({"ref": ref, "reason": "no_direct_excerpt_origin"})
            continue

        if not exact_excerpt or exact_excerpt.lower() in {"未披露", "未知", "not disclosed"}:
            failures.append({"ref": ref, "reason": "empty_or_placeholder_excerpt"})
            continue
        records.append(
            {
                "ref": ref,
                "origin_kind": origin_kind,
                "origin_detail": origin_detail,
                "excerpt_sha256": _sha256_json(exact_excerpt),
                "direct_original_excerpt": True,
            }
        )

    refs = [str(source["ref"]) for source in sources]
    record_refs = [str(record["ref"]) for record in records]
    missing = sorted(set(refs) - set(record_refs))
    duplicate_refs = sorted(
        ref for ref in set(record_refs) if record_refs.count(ref) > 1
    )
    audit = {
        "audit_version": "equipment.source_direct_excerpt.v1",
        "as_of_date": AS_OF_DATE,
        "source_count": len(refs),
        "direct_original_excerpt_count": len(records),
        "summary_rewrite_count": 0 if not failures and not missing else len(failures) + len(missing),
        "missing_direct_excerpt_refs": missing,
        "duplicate_record_refs": duplicate_refs,
        "failures": failures,
        "records": records,
        "EQ-EVID-005": "closed" if not failures and not missing and not duplicate_refs else "open",
        "status": "pass" if not failures and not missing and not duplicate_refs else "fail",
    }
    if audit["status"] != "pass":
        raise ValueError(f"设备来源直接摘录审计失败：{audit}")
    return audit


def _unique_refs(
    raw_refs: list[str],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    *,
    maximum: int = 7,
) -> list[str]:
    selected: list[str] = []
    groups: set[str] = set()
    for ref in raw_refs:
        source = sources_by_ref.get(ref)
        if not source:
            continue
        group = str(source.get("independence_key") or "")
        if group and group not in groups:
            groups.add(group)
            selected.append(ref)
            if len(selected) >= maximum:
                break
    if len(selected) < 5:
        raise ValueError(f"独立证据组不足：{raw_refs}")
    return selected


def _citation_text(refs: Sequence[str], *, available_refs: set[str] | None = None) -> str:
    selected = [
        str(ref)
        for ref in dict.fromkeys(refs)
        if not available_refs or str(ref) in available_refs
    ]
    if not selected:
        return "本轮没有可点击的一手证据"
    return " ".join(f"^src:source_ref:{ref}" for ref in selected)


def _refs_from_markdown(body: str) -> list[str]:
    """Derive section evidence from the citations readers can actually click."""
    return list(
        dict.fromkeys(
            re.findall(r"\^src:source_ref:([A-Za-z0-9_-]+)", body)
        )
    )


def _report_section(
    *, section_key: str, section_title: str, body_markdown: str
) -> dict[str, Any]:
    refs = _refs_from_markdown(body_markdown)
    if not refs:
        raise ValueError(f"公开章节缺少正文引用：{section_key}")
    return {
        "section_key": section_key,
        "section_title": section_title,
        "body_markdown": body_markdown,
        "support_status": "partially_supported",
        "evidence_ref_uri_list": [source_uri(ref) for ref in refs],
    }


def _factor_suggestion_catalog() -> tuple[
    dict[str, list[str]],
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, str]],
]:
    payload = _load_json(EQUIPMENT_DIR / "segment_factor_suggestions.json")
    group_sources = {
        str(group["key"]): [str(ref) for ref in group.get("source_ids") or []]
        for group in payload["evidence_group_catalog"]
    }
    segments = {
        str(segment["segment_id"]): list(segment["factors"])
        for segment in payload["segments"]
    }
    group_metadata = {
        str(group["key"]): {
            "independent_party": str(group.get("independent_party") or ""),
            "relevance": str(group.get("relevance") or ""),
        }
        for group in payload["evidence_group_catalog"]
    }
    return group_sources, segments, group_metadata


def _equipment_metric_slot_specs(
    entity_key: str,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return the small set of equipment slots backed by replayable data points.

    The absence of a slot here is intentional: the shared compiler keeps it
    missing.  In particular, annual revenue, annual shipments and monthly
    capacity never stand in for a three-month output change, and project
    capacity never stands in for an equipment order.
    """

    common: dict[str, dict[str, dict[str, Any]]] = {
        "demand.customer_capex_capacity_signal": {
            "confirmed_capacity_expansion_event": {
                "selectors": [
                    {"title": "奕斯伟武汉硅片项目：规划月产能"},
                    {"title": "奕斯伟武汉硅片项目：设备搬入时间"},
                ],
                "raw_unit": "万片/月与计划时间",
                "standardized_value_text": "项目业主披露60万片/月规划，并给出2026年第四季度设备搬入节点",
                "standardized_unit": "项目状态",
                "normalization_method": "把同一业主、同一项目的规划产能与设备搬入节点合并为一个扩产事件；不把规划写成已投产或已下单。",
                "bucket": "已确认项目，设备订单尚未披露",
                "slot_score": 68.0,
                "scoring_rule": "业主同时披露产能与设备搬入节点记68分；只有产能意向记55分；已投产且验收记80分。",
                "as_of_date": "2026-05-24",
            }
        },
        "demand.output_consumption_proxy": {
            "industry_sales_growth": {
                "selectors": [{"title": "全球硅晶圆市场：销售额同比"}],
                "standardized_value_num": -1.2,
                "standardized_unit": "%同比",
                "normalization_method": "直接采用SEMI同口径2025年全球硅晶圆销售额同比变化；不与出货面积增速混算。",
                "bucket": "销售额小幅收缩",
                "slot_score": 45.0,
                "scoring_rule": "按V0.8.1第9.3节：≥25%记90分；10%至25%记75分；0%至10%记60分；-10%至0%记45分；低于-10%记25分。",
                "value_status": "stale_but_usable",
                "period": "2025",
            },
            "utilization_rate_signal": {
                "selectors": [{"title": "上海超硅300毫米硅片：产能利用率"}],
                "standardized_value_num": 75.18,
                "standardized_unit": "%",
                "normalization_method": "直接采用招股书按300毫米硅片瓶颈工序计算的2025年产能利用率。",
                "bucket": "利用率中等，尚有闲置空间",
                "slot_score": 60.0,
                "scoring_rule": "≥90%记80分；80%至90%记70分；70%至80%记60分；60%至70%记50分；低于60%记35分。",
                "value_status": "stale_but_usable",
                "period": "2025",
            },
        },
        "supply.capacity_event_12m": {
            "current_effective_capacity": {
                "selectors": [{"title": "上海超硅300毫米硅片：2025年平均瓶颈月产能"}],
                "standardized_value_num": 30.58,
                "standardized_unit": "万片/月",
                "normalization_method": "用招股书2025年367万片瓶颈年产能除以12，得到平均瓶颈月产能30.58万片。",
                "bucket": "已有中等规模有效产能",
                "slot_score": 62.0,
                "scoring_rule": "≥60万片/月记75分；30至60万片/月记62分；15至30万片/月记55分；低于15万片/月记45分。",
                "value_status": "stale_but_usable",
                "period": "2025",
            },
            "planned_or_rumored_capacity": {
                "selectors": [{"title": "奕斯伟武汉硅片项目：规划月产能"}],
                "standardized_value_num": 60.0,
                "standardized_unit": "万片/月规划产能",
                "normalization_method": "直接采用项目业主最新披露的规划月产能；保留为规划槽，不转成当前有效产能。",
                "as_of_date": "2026-05-24",
            },
        },
    }

    if entity_key == "silicon_epitaxy_tools":
        common["demand.customer_capex_capacity_signal"] = {
            "confirmed_capacity_expansion_event": {
                "selectors": [
                    {"title": "上海超硅300毫米薄层外延项目：新增年产能"},
                    {"title": "上海超硅300毫米薄层外延项目：设备及安装投资"},
                ],
                "raw_unit": "万片/年与亿元人民币",
                "standardized_value_text": "规划新增180万片/年薄层外延能力，并列示27.856575亿元设备及安装投资",
                "standardized_unit": "项目状态",
                "normalization_method": "把同一募投项目的新增产能和设备预算配对；只确认正式规划，不写成已采购。",
                "bucket": "规划与设备预算均明确，尚待落地",
                "slot_score": 65.0,
                "scoring_rule": "产能与设备预算同时披露记65分；仅披露产能记55分；合同与开工均确认记78分。",
                "period": "IPO募投规划",
            },
            "equipment_order_or_billings_proxy": {
                "selectors": [
                    {"title": "上海超硅-应用材料：常压外延系统合同金额", "period": "2022-08-29签署、履行中"},
                    {"title": "上海超硅-应用材料：常压外延系统合同金额", "period": "2021-11-08签署、已完成"},
                ],
                "raw_unit": "百万美元",
                "standardized_value_num": 173.8,
                "standardized_unit": "百万美元历史合同额",
                "normalization_method": "将同一客户披露的两份常压外延系统合同128.5与45.3百万美元相加。",
                "bucket": "历史具名大额设备合同，当前项目待确认",
                "slot_score": 58.0,
                "scoring_rule": "历史具名合同超过100百万美元但无本轮订单记58分；本轮合同确认记75分；仅产品页记50分。",
                "value_status": "stale_but_usable",
                "period": "2021—2022",
            },
            "customer_delay_or_cut_event": {
                "selectors": [
                    {"title": "立昂微12英寸外延项目：工程进度"},
                    {"title": "立昂微12英寸外延项目：计划完成时间"},
                ],
                "raw_unit": "%与计划时间",
                "standardized_value_text": "工程进度20.60%，项目达到预定可使用状态延期至2027年12月",
                "standardized_unit": "延期状态",
                "normalization_method": "把年报披露的工程进度与最新完成日期合并，并按原文延期说明归入反证槽。",
                "bucket": "明确放缓设备采购并延期",
                "slot_score": 25.0,
                "scoring_rule": "明确取消记15分；明确延期且放缓采购记25分；只有进度偏慢但未延期记38分。",
                "as_of_date": "2025-12-31",
            },
        }
        common["supply.capacity_event_12m"]["planned_or_rumored_capacity"] = {
            "selectors": [{"title": "上海超硅300毫米薄层外延项目：新增年产能"}],
            "standardized_value_num": 15.0,
            "standardized_unit": "万片/月规划产能",
            "normalization_method": "将规划新增180万片/年除以12，标准化为15万片/月；仍保留为规划产能。",
            "period": "IPO募投规划",
        }
        common["supply.capacity_event_12m"]["ramp_delay_or_cancel_event"] = {
            "selectors": [
                {"title": "立昂微12英寸外延项目：工程进度"},
                {"title": "立昂微12英寸外延项目：计划完成时间"},
            ],
            "raw_unit": "%与计划时间",
            "standardized_value_text": "工程进度20.60%，设备采购节奏放缓，完成日期延期至2027年12月",
            "standardized_unit": "爬坡延期状态",
            "normalization_method": "按年报原文把工程进度、设备采购放缓和延期日期合并为项目爬坡反证。",
            "bucket": "延期使未来十二个月有效新增供给更难兑现",
            "slot_score": 80.0,
            "scoring_rule": "该槽从供给紧张方向评分：确认取消记90分；确认延期且设备采购放缓记80分；只有轻微爬坡延迟记65分；按期量产记45分。",
            "as_of_date": "2025-12-31",
        }
        common["supply.expansion_cycle_bucket"] = {
            "expansion_cycle_months_or_bucket": {
                "selectors": [{"title": "上海超硅300毫米薄层外延项目：建设期"}],
                "standardized_value_num": 24.0,
                "standardized_unit": "月",
                "normalization_method": "直接采用募投项目披露的建设期。",
                "bucket": "两年建设周期",
                "slot_score": 85.0,
                "scoring_rule": "按V0.8.1第9.6节，并约定24个月进入24至36个月档：大于36个月记95分；24至36个月（含边界）记85分；12至不足24个月记65分；6至不足12个月记45分；不足6个月记25分。",
                "period": "IPO募投规划",
            },
        }
        common["supply.substitution_barrier"] = {
            "process_criticality_bucket": {
                "selectors": [
                    {"title": "上海超硅-应用材料：常压外延系统合同金额", "period": "2022-08-29签署、履行中"},
                    {"title": "上海超硅-应用材料：常压外延系统合同金额", "period": "2021-11-08签署、已完成"},
                ],
                "raw_unit": "百万美元",
                "standardized_value_num": 173.8,
                "standardized_unit": "百万美元历史合同额",
                "normalization_method": "将两份具名常压外延系统合同金额相加，用作设备工序重要性的历史代理，不外推当前份额。",
                "bucket": "高价值关键系统",
                "slot_score": 82.0,
                "scoring_rule": "同一硅片厂具名系统合同≥100百万美元记82分；30至100百万美元记68分；无合同金额只保留缺失。",
                "value_status": "stale_but_usable",
                "period": "2021—2022",
            }
        }
    else:
        common["demand.customer_capex_capacity_signal"]["equipment_order_or_billings_proxy"] = {
            "selectors": [],
        }

    if entity_key == "wafer_grinding_polishing_tools":
        common["demand.customer_capex_capacity_signal"]["equipment_order_or_billings_proxy"] = {
            "selectors": [{"title": "上海超硅-招股书匿名研磨设备供应商：研磨机合同金额"}],
            "standardized_value_num": 29.376,
            "standardized_unit": "百万美元历史合同额",
            "normalization_method": "直接采用上海超硅招股书列示的匿名研磨设备供应商合同金额；不把月产能或项目总投资代入。",
            "bucket": "历史具名设备合同，当前项目待确认",
            "slot_score": 55.0,
            "scoring_rule": "历史设备合同20至50百万美元且无本轮订单记55分；本轮具名合同记72分；无设备合同保持缺失。",
            "value_status": "stale_but_usable",
            "period": "2022-04-27签署、履行中",
        }
        common["demand.application_intensity_change"] = {
            "technology_generation_shift": {
                "selectors": [{"title": "上海超硅SOI工艺：氢离子注入剥离型SOI专有工序"}],
                "standardized_value_num": 7.0,
                "standardized_unit": "个披露工序",
                "normalization_method": "逐项计数原文列示的氧化、注入、键合、退火剥离、平坦化减薄、表面处理和再键合七项工序。",
                "bucket": "SOI显著增加研磨和平坦化相关工序",
                "slot_score": 82.0,
                "scoring_rule": "新增或强化工序≥6项记82分；3至5项记68分；1至2项记55分。",
                "period": "2026招股书研发披露",
            }
        }
        common["supply.supplier_structure_bucket"] = {
            "qualification_bottleneck_text": {
                "selectors": [
                    {"title": "西安奕材采购自浙江芯晖装备的研磨减薄设备：采购数量"},
                    {"title": "西安奕材采购自浙江芯晖装备的研磨减薄设备：已完成验收数量"},
                    {"title": "西安奕材采购自浙江芯晖装备的研磨减薄设备：合同累计付款比例"},
                ],
                "raw_unit": "台与付款比例",
                "standardized_value_num": 0.0,
                "standardized_unit": "%最终验收率",
                "normalization_method": "以已完成验收0台除以采购3台得到0%；付款90%只作验收不能由付款替代的旁证。",
                "bucket": "最终验收瓶颈高",
                "slot_score": 85.0,
                "scoring_rule": "最终验收率<25%记85分；25%至75%记65分；≥75%记45分。",
                "as_of_date": "2026问询回复时点",
            }
        }
        common["supply.substitution_barrier"] = {
            "process_criticality_bucket": {
                "selectors": [{"title": "上海超硅200/300毫米硅片线：主要瓶颈设备"}],
                "standardized_value_text": "抛光机是300毫米和200毫米生产线的瓶颈设备",
                "standardized_unit": "瓶颈状态",
                "normalization_method": "直接采用发行人按瓶颈工序测算产能时对抛光机的定位。",
                "bucket": "关键瓶颈工序",
                "slot_score": 85.0,
                "scoring_rule": "发行人明确列为产能瓶颈记85分；仅列入一般工序记60分；非必经工序记40分。",
                "period": "2025",
            },
            "commercial_alternative_status": {
                "selectors": [
                    {"title": "西安奕材采购自浙江芯晖装备的CMP设备：采购数量"},
                    {"title": "西安奕材采购自浙江芯晖装备的CMP设备：已转固数量"},
                    {"title": "西安奕材采购自浙江芯晖装备的研磨减薄设备：采购数量"},
                    {"title": "西安奕材采购自浙江芯晖装备的研磨减薄设备：已完成验收数量"},
                ],
                "raw_unit": "台",
                "standardized_value_text": "国产CMP设备5/5已转固，国产研磨减薄设备0/3完成最终验收",
                "standardized_unit": "分产品验证状态",
                "normalization_method": "分别计算CMP转固率5÷5=100%与研磨减薄最终验收率0÷3=0%，不跨产品合并平均。",
                "bucket": "国产替代成熟度按产品明显分化",
                "slot_score": 55.0,
                "scoring_rule": "两类设备均完成验证记35分；仅一类完成记55分；两类均未完成记80分。",
                "as_of_date": "2026问询回复时点",
            },
            "switching_validation_burden": {
                "selectors": [
                    {"title": "西安奕材采购自浙江芯晖装备的研磨减薄设备：采购数量"},
                    {"title": "西安奕材采购自浙江芯晖装备的研磨减薄设备：已完成验收数量"},
                    {"title": "西安奕材采购自浙江芯晖装备的研磨减薄设备：合同累计付款比例"},
                ],
                "raw_unit": "台与付款比例",
                "standardized_value_num": 0.0,
                "standardized_unit": "%最终验收率",
                "normalization_method": "以0台最终验收除以3台采购量得到0%；同时保留90%已付款这一不能替代验收的反差。",
                "bucket": "切换验证负担很高",
                "slot_score": 90.0,
                "scoring_rule": "最终验收率<25%且已付款≥75%记90分；验收率25%至75%记70分；≥75%记45分。",
                "as_of_date": "2026问询回复时点",
            },
        }

    if entity_key in {"wafer_grinding_polishing_tools", "bare_wafer_metrology_tools", "wafer_final_clean_automation"}:
        common.setdefault("demand.application_intensity_change", {})[
            "technology_generation_shift"
        ] = {
            "selectors": [{"title": "上海超硅SOI工艺：氢离子注入剥离型SOI专有工序"}],
            "standardized_value_num": 7.0,
            "standardized_unit": "个披露工序",
            "normalization_method": "逐项计数原文列示的氧化、注入、键合、退火剥离、平坦化减薄、表面处理和再键合七项工序。",
            "bucket": "SOI显著增加专有制造工序",
            "slot_score": 82.0,
            "scoring_rule": "新增或强化工序≥6项记82分；3至5项记68分；1至2项记55分。",
            "period": "2026招股书研发披露",
        }

    if entity_key == "bare_wafer_metrology_tools":
        common["demand.customer_capex_capacity_signal"]["equipment_order_or_billings_proxy"] = {
            "selectors": [
                {"title": "上海超硅-KLA：缺陷/表面质量检测设备合同金额", "period": "2023-03-01签署、履行中"},
                {"title": "上海超硅-KLA：缺陷/表面质量检测设备合同金额", "period": "2023-03-15签署、已完成"},
                {"title": "上海超硅-KLA：晶圆几何量测设备合同金额"},
            ],
            "raw_unit": "百万美元",
            "standardized_value_num": 190.07,
            "standardized_unit": "百万美元历史合同额",
            "normalization_method": "将KLA三份具名检测与量测设备合同93.77、33.00和63.30百万美元相加。",
            "bucket": "历史具名大额设备合同，当前项目待确认",
            "slot_score": 60.0,
            "scoring_rule": "历史具名合同超过100百万美元但无本轮订单记60分；本轮订单确认记78分；无设备合同保持缺失。",
            "value_status": "stale_but_usable",
            "period": "2022—2023",
        }
        common["supply.substitution_barrier"] = {
            "process_criticality_bucket": {
                "selectors": [
                    {"title": "上海超硅-KLA：缺陷/表面质量检测设备合同金额", "period": "2023-03-01签署、履行中"},
                    {"title": "上海超硅-KLA：缺陷/表面质量检测设备合同金额", "period": "2023-03-15签署、已完成"},
                    {"title": "上海超硅-KLA：晶圆几何量测设备合同金额"},
                ],
                "raw_unit": "百万美元",
                "standardized_value_num": 190.07,
                "standardized_unit": "百万美元历史合同额",
                "normalization_method": "合计三份具名检测与量测合同，作为该硅片厂质量控制工序价值和重要性的历史代理。",
                "bucket": "高价值关键检测工序",
                "slot_score": 88.0,
                "scoring_rule": "同一硅片厂具名合同≥150百万美元记88分；50至150百万美元记72分；无合同金额保持缺失。",
                "value_status": "stale_but_usable",
                "period": "2022—2023",
            }
        }

    # Empty selector sentinels are never compiled into usable slots.
    for factor_code in list(common):
        common[factor_code] = {
            slot_code: slot
            for slot_code, slot in common[factor_code].items()
            if slot.get("selectors")
        }
    return common


def _metric_slot_payload(
    *,
    entity_key: str,
    factor_code: str,
    data_points_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    slot_specs = _equipment_metric_slot_specs(entity_key).get(factor_code, {})
    all_points = [point for rows in data_points_by_source.values() for point in rows]
    candidates: dict[str, dict[str, Any]] = {}
    metric_slot_inputs: dict[str, dict[str, Any]] = {}
    required_refs: list[str] = []
    generic_locators = {"", "原始网页或PDF所列段落", "原始网页所列段落"}

    for slot_code, raw_spec in slot_specs.items():
        spec = dict(raw_spec)
        selected: list[Mapping[str, Any]] = []
        for selector in spec.pop("selectors"):
            matches = [
                point
                for point in all_points
                if point.get("data_point_title") == selector["title"]
                and (
                    selector.get("period") is None
                    or point.get("period") == selector["period"]
                )
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"{entity_key}.{factor_code}.{slot_code} 数据点选择不唯一："
                    f"{selector} -> {len(matches)}"
                )
            selected.append(matches[0])
        data_point_keys: list[str] = []
        for point in selected:
            ref = str(point.get("source_ref") or "")
            source = sources_by_ref.get(ref)
            if not source:
                raise ValueError(f"指标槽数据点引用未知来源：{ref}")
            locator = str(source.get("local_locator") or source.get("url") or "").strip()
            excerpt = str(source.get("excerpt_zh") or source.get("excerpt") or "").strip()
            if locator in generic_locators or len(excerpt) < 30:
                raise ValueError(
                    f"{entity_key}.{factor_code}.{slot_code} 来源{ref}缺少精确定位或忠实摘录"
                )
            key = str(point.get("data_point_key") or "").strip()
            candidate = {
                "data_point_key": key,
                "data_point_title": str(point.get("data_point_title") or ""),
                "metric": str(point.get("metric") or ""),
                "unit": str(point.get("unit") or ""),
                "value_num": point.get("value_num"),
                "value_text": point.get("value_text"),
                "period": str(point.get("period") or ""),
                "source_ref": ref,
            }
            candidates[key] = candidate
            data_point_keys.append(key)
            required_refs.append(ref)
        spec["data_point_keys"] = data_point_keys
        metric_slot_inputs[slot_code] = spec

    return list(candidates.values()), metric_slot_inputs, list(dict.fromkeys(required_refs))


def _factor_inputs(
    spec: Mapping[str, Any],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    data_points_by_source: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    group_sources, segments, group_metadata = _factor_suggestion_catalog()
    segment_id = SEGMENT_ID_BY_ENTITY[str(spec["key"])]
    custom_factors = segments[segment_id]
    if len(custom_factors) != 10:
        raise ValueError(f"{segment_id} 自定义设备因子不是10项")
    score_map = EQUIPMENT_FACTOR_SCORES[str(spec["key"])]
    if set(score_map) != set(SEGMENT_FACTOR_CODES):
        raise ValueError(f"{spec['key']} 缺少逐因子显式评分")
    inputs: dict[str, Any] = {}
    risk_clause = str(spec["risk"])
    if risk_clause.startswith("若"):
        risk_clause = risk_clause[1:]
    confidence_base = 0.77 if int(spec["base_score"]) >= 65 else 0.68

    def entity_detail(code: str) -> str:
        name = str(spec["name"])
        details = {
            "demand.downstream_price_momentum": (
                f"对{name}，价格和利用率必须先覆盖新增设备的折旧与验证成本；"
                f"主要反方是{risk_clause}"
            ),
            "demand.customer_capex_capacity_signal": (
                f"本轮最直接的项目判断是{str(spec['focus']).rstrip('。')}；"
                "只有资金、搬入和采购节点继续推进，才会形成当前需求"
            ),
            "demand.output_consumption_proxy": (
                f"数量换算采用的边界是{str(spec['method']).rstrip('。')}；"
                "缺少这些输入时只保留金额区间"
            ),
            "demand.application_intensity_change": (
                f"本工序边界是{str(spec['description']).rstrip('。')}；"
                "高规格需求带来的新增步骤必须落到对应产品和客户规格"
            ),
            "supply.capacity_event_12m": (
                f"未来一年优先核对{str(spec['follow_up']).rstrip('。')}；"
                "未进入搬入、转固或验收阶段的远期项目不计作近端订单"
            ),
            "supply.expansion_cycle_bucket": (
                f"{name}从合同到收入必须跨过交付、调试和最终验收；"
                f"主要风险是{risk_clause.rstrip('。')}；一旦发生，收入确认会继续后移"
            ),
            "supply.raw_policy_constraint": (
                f"政策只能改变{name}的采购可达范围；供应格局仍需依据"
                f"{str(spec['competition']).rstrip('。')}来确认"
            ),
            "supply.supplier_structure_bucket": (
                f"当前竞争证据显示{str(spec['competition']).rstrip('。')}；"
                "比较对象必须限定在同一尺寸、同一工序和同一验证阶段"
            ),
            "supply.substitution_barrier": (
                f"{name}能否替代既有平台取决于量产质量而非产品名称；"
                f"{risk_clause}"
            ),
            "signal.material_price_momentum": (
                f"订单价格最终要与{name}的专题收入和回款核对；"
                f"目前{str(spec['financial']).rstrip('。')}"
            ),
        }
        return details[code]

    for code in SEGMENT_FACTOR_CODES:
        label, note = FACTOR_NOTES[code]
        frame = FACTOR_PUBLIC_FRAMES[code]
        routed = [custom_factors[index] for index in EQUIPMENT_FACTOR_ROUTES[code]]
        group_keys = [
            str(group_key)
            for factor in routed
            for group_key in factor.get("evidence_group_keys") or []
        ]
        if code == "supply.raw_policy_constraint":
            group_keys = [*EQUIPMENT_POLICY_GROUPS, *group_keys]
        measurement = "；".join(
            dict.fromkeys(str(factor["measurement"]) for factor in routed)
        )
        selection_query = " ".join(
            (
                label,
                frame["question"],
                frame["evidence_lens"],
                measurement,
                str(spec["name"]),
            )
        )
        candidate_data_points, metric_slot_inputs, required_refs = _metric_slot_payload(
            entity_key=str(spec["key"]),
            factor_code=code,
            data_points_by_source=data_points_by_source or {},
            sources_by_ref=sources_by_ref,
        )
        refs: list[str] = []
        used_groups: set[str] = set()

        def add_ref(ref: str, *, require_new_group: bool) -> None:
            source = sources_by_ref.get(ref)
            if not source or ref in refs:
                return
            group = str(source.get("independence_key") or "")
            if require_new_group and group in used_groups:
                return
            refs.append(ref)
            if group:
                used_groups.add(group)

        # Every usable metric input must remain attached even when two inputs
        # come from the same issuer. Additional sources are selected only from
        # the groups routed to this factor; entity-wide boilerplate refs are not
        # permitted to leak into unrelated factor evidence.
        for ref in required_refs:
            add_ref(ref, require_new_group=False)
        for group_key in dict.fromkeys(group_keys):
            ranked_group_refs = sorted(
                (str(ref) for ref in group_sources.get(group_key, [])),
                key=lambda ref: _source_excerpt_similarity(
                    selection_query,
                    " ".join(
                        str(sources_by_ref.get(ref, {}).get(field) or "")
                        for field in (
                            "title",
                            "title_zh",
                            "excerpt",
                            "excerpt_zh",
                            "local_locator",
                        )
                    ),
                ),
                reverse=True,
            )
            for ref in ranked_group_refs:
                before = len(refs)
                add_ref(ref, require_new_group=True)
                if len(refs) > before:
                    break
            if len(refs) >= 7:
                break
        if len(used_groups) < 5:
            raise ValueError(
                f"{spec['key']}.{code} 路由后独立证据组不足：groups={sorted(used_groups)}"
            )
        if len(refs) > 7:
            raise ValueError(f"{spec['key']}.{code} 必需来源超过公开上限：{refs}")
        score = int(score_map[code])
        coverage = 0.84 if len(refs) >= 7 else 0.79
        confidence = confidence_base
        if code in {"demand.downstream_price_momentum", "signal.material_price_momentum"}:
            confidence -= 0.08
        elif code in {"demand.customer_capex_capacity_signal", "supply.substitution_barrier"}:
            confidence += 0.03
        factor_entity_detail = entity_detail(code)
        ref_to_group: dict[str, str] = {}
        for group_key in group_keys:
            for ref in group_sources.get(group_key, []):
                ref_to_group.setdefault(str(ref), str(group_key))
        evidence_parties = list(
            dict.fromkeys(
                group_metadata.get(ref_to_group.get(ref, ""), {}).get(
                    "independent_party",
                    str(sources_by_ref[ref].get("publisher") or "来源发布方"),
                )
                for ref in refs
            )
        )
        evidence_interpretations: dict[str, str] = {}
        required_titles_by_ref: dict[str, list[str]] = {}
        for point in candidate_data_points:
            required_titles_by_ref.setdefault(str(point.get("source_ref") or ""), []).append(
                str(point.get("data_point_title") or point.get("metric") or "")
            )
        for ref in refs:
            if required_titles_by_ref.get(ref):
                role = "、".join(dict.fromkeys(required_titles_by_ref[ref]))
                evidence_interpretations[ref] = (
                    f"用于回答“{frame['question']}”：该来源直接提供{role}，并进入本项可复算事实；"
                    "它不被外推为未披露的设备订单或公司份额。"
                )
                continue
            group_key = ref_to_group.get(ref, "")
            metadata = group_metadata.get(group_key, {})
            evidence_interpretations[ref] = (
                f"用于回答“{frame['question']}”：{metadata.get('independent_party') or sources_by_ref[ref].get('publisher')}"
                f"直接披露{metadata.get('relevance') or frame['evidence_lens']}；"
                "本项把这项事实作为正面依据、反方约束或时点背景，"
                f"不把它扩大成对{frame['evidence_lens']}所有环节的证明。"
            )
        inputs[code] = {
            "metric_name": f"{spec['name']}的{label}",
            "period": "2026—2030",
            "unit": "分",
            "score_raw": score,
            "score_adjusted": score,
            "coverage": round(coverage, 2),
            "confidence": round(confidence, 2),
            "score_rationale": (
                f"{spec['name']}的“{label}”由{len(used_groups)}个独立发布主体交叉核对，具体比较{measurement}。"
                f"现有证据支持{score}分的研究排序，但{frame['risk_test']}，因此不能把该分数解释成订单概率或收益率。"
            ),
            "factor_value_summary": (
                f"{spec['name']}的{label}结论是：{frame['conclusion']}。"
                f"{factor_entity_detail}。"
            ),
            "source_context_summary": (
                f"本项使用{'、'.join(evidence_parties)}等独立发布方，分别核对{frame['evidence_lens']}。"
                "同一发行人的年报、公告和问询回复合并理解，避免把同一事实重复计证。"
            ),
            "factor_topic_analysis": (
                f"要回答“{frame['question']}”，本研究比较以下方面：{measurement.rstrip('；。')}。{note}"
                f"对{spec['name']}，现有资料指向“{frame['conclusion']}”；"
                f"具体到本工序，{factor_entity_detail}。"
                f"反方检验是：{frame['risk_test']}。"
            ),
            "theme_analysis_points": [
                f"当前证据：{factor_entity_detail}；本项重点核对{frame['evidence_lens']}。",
                f"反方情景：{frame['risk_test']}；此外，{risk_clause}时也应下调判断。",
                f"如果想进一步研究，需要补充{frame['follow_up']}，并与{spec['follow_up']}交叉验证。",
            ],
            "source_refs": refs,
            "candidate_data_points": candidate_data_points,
            "metric_slot_inputs": metric_slot_inputs,
            "evidence_interpretations": evidence_interpretations,
            "factor_readiness_status": "ready",
        }
    return inputs


def _apply_factor_specific_information_excerpts(
    entity: dict[str, Any],
    *,
    data_points_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> None:
    points_by_key = {
        str(point.get("data_point_key") or ""): point
        for points in data_points_by_source.values()
        for point in points
        if str(point.get("data_point_key") or "")
    }
    for factor in entity.get("factor_scores") or []:
        query = " ".join(
            str(factor.get(field) or "")
            for field in (
                "metric_name",
                "factor_value_summary",
                "factor_topic_analysis",
                "score_rationale",
            )
        )
        required_keys_by_ref: dict[str, list[str]] = {}
        for slot in factor.get("metric_slots") or []:
            for key in slot.get("data_point_keys") or []:
                point = points_by_key.get(str(key))
                if not point:
                    continue
                required_keys_by_ref.setdefault(
                    str(point.get("source_ref") or ""), []
                ).append(str(key))
        for information_point in factor.get("information_points") or []:
            ref = str(information_point.get("evidence_ref") or "").replace(
                "source_ref:", ""
            )
            candidates = list(data_points_by_source.get(ref) or [])
            if candidates:
                required_keys = set(required_keys_by_ref.get(ref) or [])
                if required_keys:
                    candidates = [
                        point
                        for point in candidates
                        if str(point.get("data_point_key") or "") in required_keys
                    ]
                public_candidates = [
                    point
                    for point in candidates
                    if not any(
                        token in str(point.get(field) or "")
                        for token in ("供应商B1", "匿名供应商B1", "日本精工类")
                        for field in ("data_point_title", "metric", "source_excerpt")
                    )
                ]
                if public_candidates:
                    candidates = public_candidates
                selected = max(
                    candidates,
                    key=lambda point: _source_excerpt_similarity(
                        query,
                        " ".join(
                            str(point.get(field) or "")
                            for field in (
                                "data_point_title",
                                "metric",
                                "interpretation",
                                "research_use",
                            )
                        ),
                    ),
                )
                information_point["excerpt"] = str(
                    selected.get("source_excerpt") or ""
                ).strip()
                source_language = str(
                    sources_by_ref[ref].get("language") or ""
                ).lower()
                if source_language.startswith("zh"):
                    information_point.pop("excerpt_zh", None)
                else:
                    translated = str(selected.get("source_excerpt_zh") or "").strip()
                    if not translated:
                        raise ValueError(
                            f"{entity.get('key')}.{factor.get('factor_code')} 的英文数据点"
                            f"{selected.get('data_point_key')}缺少同条中文译意"
                        )
                    information_point["excerpt_zh"] = translated
            else:
                source = sources_by_ref[ref]
                information_point["excerpt"] = str(
                    source.get("excerpt") or ""
                ).strip()
                source_language = str(source.get("language") or "").lower()
                translated = str(source.get("excerpt_zh") or "").strip()
                if source_language.startswith("zh"):
                    information_point.pop("excerpt_zh", None)
                else:
                    if not translated:
                        raise ValueError(
                            f"{entity.get('key')}.{factor.get('factor_code')} 的英文来源{ref}缺少中文译意"
                        )
                    information_point["excerpt_zh"] = translated


def _rewrite_factor_score_rationales(entity: dict[str, Any]) -> None:
    """Keep unrated text qualitative and reconcile every published score to its fields."""

    for factor in entity.get("factor_scores") or []:
        if str(factor.get("score_status") or "") == "complete":
            raw = float(factor["score_raw"])
            adjusted = float(factor["score_adjusted"])
            factor["score_rationale"] = (
                "本项已有可用指标和来源证据，可以进行量化比较；"
                f"调整后分{adjusted:.1f}，原始分{raw:.1f}。"
                "调整反映证据覆盖、来源可靠性和输入完整性，不代表订单概率或投资收益率。"
            )
            continue
        code = str(factor.get("factor_code") or "")
        frame = FACTOR_PUBLIC_FRAMES[code]
        risk = str(frame["risk_test"]).removeprefix("若").rstrip("。")
        factor["score_rationale"] = (
            f"公开资料目前支持“{frame['conclusion']}”。"
            f"但还缺少{frame['follow_up']}，现有输入无法形成可复算、可横向比较的量化判断。"
            f"若{risk}，本项结论需要下调。"
        )


def _build_factor_public_content_audit(
    *,
    pack: Mapping[str, Any],
    data_points_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    sources_by_ref = {
        str(source["ref"]): source for source in pack.get("sources") or []
    }
    points_by_key = {
        str(point.get("data_point_key") or ""): point
        for points in data_points_by_source.values()
        for point in points
        if str(point.get("data_point_key") or "")
    }
    group_sources, segments, _group_metadata = _factor_suggestion_catalog()
    failures: list[dict[str, str]] = []
    duplicate_failures: list[dict[str, Any]] = []
    forbidden_pattern = re.compile(
        r"canonical|intake|参数\s*owner|字段完成|完成矩阵|D0/D1/D2|本轮代理|专属边界",
        re.IGNORECASE,
    )
    unrated_public_score_pattern = re.compile(r"\d+(?:\.\d+)?\s*分|研究排序|评分为")
    unreadable_phrase_pattern = re.compile(
        r"只覆盖覆盖|会使确认时间继续后移|按按|分开逐项比较"
    )
    rated_score_pattern = re.compile(
        r"调整后分(?P<adjusted>\d+(?:\.\d+)?)，原始分(?P<raw>\d+(?:\.\d+)?)"
    )
    factor_count = 0
    source_role_failure_count = 0
    unrated_factor_count = 0
    unrated_public_score_leak_count = 0
    rated_factor_count = 0
    rated_score_reconciliation_failure_count = 0
    for entity in pack.get("entities") or []:
        entity_key = str(entity.get("key") or "")
        segment_id = SEGMENT_ID_BY_ENTITY[entity_key]
        custom_factors = segments[segment_id]
        public_texts: dict[str, list[str]] = {
            field: []
            for field in (
                "factor_value_summary",
                "source_context_summary",
                "factor_topic_analysis",
                "score_rationale",
            )
        }
        for factor in entity.get("factor_scores") or []:
            factor_count += 1
            code = str(factor.get("factor_code") or "")
            frame = FACTOR_PUBLIC_FRAMES[code]
            routed = [custom_factors[index] for index in EQUIPMENT_FACTOR_ROUTES[code]]
            group_keys = [
                str(group_key)
                for row in routed
                for group_key in row.get("evidence_group_keys") or []
            ]
            if code == "supply.raw_policy_constraint":
                group_keys = [*EQUIPMENT_POLICY_GROUPS, *group_keys]
            allowed_refs = {
                str(ref)
                for group_key in group_keys
                for ref in group_sources.get(group_key, [])
            }
            allowed_refs.update(
                str(ref)
                for slot in factor.get("metric_slots") or []
                for ref in slot.get("source_refs") or []
            )
            actual_refs = [
                str(value).replace("source_ref:", "")
                for value in factor.get("evidence_ref_uri_list") or []
            ]
            outside = sorted(set(actual_refs) - allowed_refs)
            if outside:
                failures.append(
                    {
                        "entity_key": entity_key,
                        "factor_code": code,
                        "reason": f"factor_route_outside_refs:{outside}",
                    }
                )
            information_by_ref = {
                str(point.get("evidence_ref") or "").replace("source_ref:", ""): point
                for point in factor.get("information_points") or []
            }
            required_keys_by_ref: dict[str, list[str]] = {}
            for slot in factor.get("metric_slots") or []:
                for key in slot.get("data_point_keys") or []:
                    data_point = points_by_key.get(str(key))
                    if data_point:
                        required_keys_by_ref.setdefault(
                            str(data_point.get("source_ref") or ""), []
                        ).append(str(key))
            for ref in actual_refs:
                point = information_by_ref.get(ref) or {}
                interpretation = str(point.get("interpretation") or "").strip()
                if frame["question"] not in interpretation or len(interpretation) < 45:
                    source_role_failure_count += 1
                    failures.append(
                        {
                            "entity_key": entity_key,
                            "factor_code": code,
                            "reason": f"source_role_missing_or_generic:{ref}",
                        }
                    )
                excerpt = str(point.get("excerpt") or "").strip()
                excerpt_zh = str(point.get("excerpt_zh") or "").strip()
                source = sources_by_ref.get(ref) or {}
                allowed_pairs = {
                    (
                        str(source.get("excerpt") or "").strip(),
                        str(source.get("excerpt_zh") or "").strip(),
                    )
                }
                for data_point in data_points_by_source.get(ref) or []:
                    allowed_pairs.add(
                        (
                            str(data_point.get("source_excerpt") or "").strip(),
                            str(data_point.get("source_excerpt_zh") or "").strip(),
                        )
                    )
                allowed_original_excerpts = {pair[0] for pair in allowed_pairs if pair[0]}
                if excerpt not in allowed_original_excerpts:
                    failures.append(
                        {
                            "entity_key": entity_key,
                            "factor_code": code,
                            "reason": f"information_excerpt_not_direct:{ref}",
                        }
                    )
                required_keys = required_keys_by_ref.get(ref) or []
                if required_keys:
                    required_originals = {
                        str(points_by_key[key].get("source_excerpt") or "").strip()
                        for key in required_keys
                    }
                    if excerpt not in required_originals:
                        failures.append(
                            {
                                "entity_key": entity_key,
                                "factor_code": code,
                                "reason": f"metric_input_excerpt_mismatch:{ref}",
                            }
                        )
                source_language = str(source.get("language") or "").lower()
                if source_language.startswith("zh") and excerpt_zh:
                    failures.append(
                        {
                            "entity_key": entity_key,
                            "factor_code": code,
                            "reason": f"chinese_information_point_has_duplicate_translation:{ref}",
                        }
                    )
                elif not source_language.startswith("zh") and (
                    not excerpt_zh or (excerpt, excerpt_zh) not in allowed_pairs
                ):
                    failures.append(
                        {
                            "entity_key": entity_key,
                            "factor_code": code,
                            "reason": f"information_translation_missing_or_unbound:{ref}",
                        }
                    )

            narrative_payload = {
                field: str(factor.get(field) or "").strip()
                for field in public_texts
            }
            narrative_payload["theme_analysis_points"] = " ".join(
                str(value) for value in factor.get("theme_analysis_points") or []
            )
            narrative_payload["information_interpretations"] = " ".join(
                str(value.get("interpretation") or "")
                for value in factor.get("information_points") or []
            )
            for field, value in narrative_payload.items():
                if forbidden_pattern.search(value):
                    failures.append(
                        {
                            "entity_key": entity_key,
                            "factor_code": code,
                            "reason": f"forbidden_public_term:{field}",
                        }
                    )
                if unreadable_phrase_pattern.search(value):
                    failures.append(
                        {
                            "entity_key": entity_key,
                            "factor_code": code,
                            "reason": f"unreadable_public_phrase:{field}",
                        }
                    )
            if str(factor.get("score_status") or "") != "complete":
                unrated_factor_count += 1
                for field, value in narrative_payload.items():
                    if unrated_public_score_pattern.search(value):
                        unrated_public_score_leak_count += 1
                        failures.append(
                            {
                                "entity_key": entity_key,
                                "factor_code": code,
                                "reason": f"unrated_public_score_leak:{field}",
                            }
                        )
            else:
                rated_factor_count += 1
                rationale = narrative_payload["score_rationale"]
                match = rated_score_pattern.search(rationale)
                expected_raw = round(float(factor.get("score_raw") or 0.0), 1)
                expected_adjusted = round(float(factor.get("score_adjusted") or 0.0), 1)
                if (
                    not match
                    or round(float(match.group("raw")), 1) != expected_raw
                    or round(float(match.group("adjusted")), 1) != expected_adjusted
                ):
                    rated_score_reconciliation_failure_count += 1
                    failures.append(
                        {
                            "entity_key": entity_key,
                            "factor_code": code,
                            "reason": "rated_score_text_does_not_match_structured_values",
                        }
                    )
            for field in public_texts:
                public_texts[field].append(narrative_payload[field])

        for field, values in public_texts.items():
            if len(values) != len(set(values)):
                duplicate_failures.append(
                    {
                        "entity_key": entity_key,
                        "field": field,
                        "reason": "exact_duplicate",
                    }
                )
            threshold = 0.93 if field in {"factor_value_summary", "factor_topic_analysis"} else 0.96
            for left_index, left in enumerate(values):
                for right_index in range(left_index + 1, len(values)):
                    ratio = _source_excerpt_similarity(left, values[right_index])
                    if ratio >= threshold:
                        duplicate_failures.append(
                            {
                                "entity_key": entity_key,
                                "field": field,
                                "factor_pair": [left_index + 1, right_index + 1],
                                "similarity": round(ratio, 4),
                            }
                        )

    audit = {
        "audit_version": "equipment.factor_public_content.v1",
        "as_of_date": AS_OF_DATE,
        "entity_count": len(pack.get("entities") or []),
        "factor_count": factor_count,
        "source_role_failure_count": source_role_failure_count,
        "unrated_factor_count": unrated_factor_count,
        "unrated_public_score_leak_count": unrated_public_score_leak_count,
        "rated_factor_count": rated_factor_count,
        "rated_score_reconciliation_failure_count": rated_score_reconciliation_failure_count,
        "duplicate_failure_count": len(duplicate_failures),
        "other_failure_count": len(failures) - source_role_failure_count,
        "failures": failures,
        "duplicate_failures": duplicate_failures,
        "status": "pass" if not failures and not duplicate_failures and factor_count == 50 else "fail",
    }
    if audit["status"] != "pass":
        raise ValueError(f"设备因子公开内容审计失败：{audit}")
    return audit


def _legacy_entity_section(spec: Mapping[str, Any], refs: list[str]) -> dict[str, Any]:
    name = spec["name"]
    risk_clause = str(spec["risk"])
    if risk_clause.startswith("若"):
        risk_clause = risk_clause[1:]
    factor_paragraphs = [
        f"需求强弱先看硅片价格、利用率和客户资本开支是否同向。对{name}而言，"
        f"{FACTOR_NOTES['demand.downstream_price_momentum'][1]}{FACTOR_NOTES['demand.customer_capex_capacity_signal'][1]}"
        f"当前公开资料显示{spec['focus']}。",
        f"设备消耗量不能只凭项目名称判断。{FACTOR_NOTES['demand.output_consumption_proxy'][1]}"
        f"同时，{FACTOR_NOTES['demand.application_intensity_change'][1]}因此，普通抛光片、外延线和工程衬底必须使用各自口径。",
        f"近端订单由搬入和验收决定。{FACTOR_NOTES['supply.capacity_event_12m'][1]}"
        f"{FACTOR_NOTES['supply.expansion_cycle_bucket'][1]}这也是为什么设备完成采购后仍可能跨年度确认收入。",
        f"供给竞争同时受到政策、关键部件和合格供应商数量约束。{FACTOR_NOTES['supply.raw_policy_constraint'][1]}"
        f"{FACTOR_NOTES['supply.supplier_structure_bucket'][1]}对{name}的排序必须以量产客户和当前项目为准。",
        f"最后检验替代壁垒和订单价格。{FACTOR_NOTES['supply.substitution_barrier'][1]}"
        f"{FACTOR_NOTES['signal.material_price_momentum'][1]}若{risk_clause}，现有判断需要下调；后续应优先补充{spec['follow_up']}。",
    ]
    factor_text = "\n\n".join(factor_paragraphs)
    body = f"""
### 要回答的问题

{name}是否会在2026—2030年形成可投资的设备需求，取决于新增硅片产能是否真的需要这一工序、设备是否进入采购与验收，以及上市公司能否把项目金额转成自己的收入。研究边界是：{spec['description']} 这避免把所有名称中带“晶圆”的前道或后道设备都纳入受益范围。

### 证据和数据

公开资料给出的核心事实是：{spec['focus']}。中国项目同时提供了已投产整线的生产设备预算、在建项目进度和若干具名采购，海外资料则更多反映已经建成后的爬坡与客户认证。两类资料的作用不同：历史投入用于校准量级，在建项目用于判断未来需求，具名合同用于确认供应关系；三者不能互相替代。相关来源按原始发行人和底层文件归并，转载没有增加证据权重。{' '.join(f'^src:source_ref:{ref}' for ref in refs[:5])}

### 估算方法

{spec['method']}。整线项目先以“新增有效月产能×每单位月产能生产设备投入”估算项目级区间，再用项目资金、施工进度和已发生支出做数量级检查。单工序设备只有在单机有效节拍、设备综合效率、良率和备机比例都能核验时才估台数。订单时点再分为正式合同、交付安装、转固或最终验收和设备商收入确认，采购周期只分配时间，不放大设备数量。

### 不同尺寸和项目不能混算

对{name}，300毫米完整抛光片线是武汉项目和两个历史校准样本的主体，设备规格、自动化和缺陷控制要求最高；200毫米产线更多服务成熟制程、功率和模拟器件，现有产能与旧设备改造的作用更大，不能沿用300毫米整线投资强度；SOI和薄层外延还增加专用外延、键合或更严格检测，其价值量应使用项目自身预算。海外项目又多已进入爬坡，因此只计算后续阶段、瓶颈和备机，不能把早年总投资再次列入未来市场。这个拆分使{name}的需求与真实产品规格相连，也防止把厂房设计能力当成已经安装的有效产能。

### 从项目金额到公司收入还隔着什么

项目级设备金额只是第一层。第二层要按{name}在整线中的工序价值占比、可服务地区和目标规格筛出供应商可以参与的部分；第三层还要核验竞争份额、合同状态、交付能力、验收条款和收入确认年度。当前公开资料没有武汉供应商分工和胜率，所以报告停止在项目区间与供应商证据排序，不输出单家公司金额。{spec['financial']}。只有合同、验收和专题收入能够相互对上，才可以进一步估算毛利和经营现金流；否则把集团毛利率乘项目预算会产生没有证据支撑的盈利数字。

### 竞争格局与结论

{spec['competition']}。综合证据，可以认为{name}具备真实需求和供应商分化，但当前结论是“优先跟踪具名合同与验收”，而不是“按项目总投资平均分配给概念公司”。因此，本实体只适合用于比较研究优先级；即使现有证据相对较强，也需要项目订单和财务穿透后才形成配置结论。

### 怎样持续判断需求是否兑现

{factor_text}

### 风险与进一步研究

主要反方是：{spec['risk']}。如果想进一步研究，需要补充{spec['follow_up']}。这些信息会把当前项目级金额继续拆成工序市场、可服务市场和供应商收入；在它们公开以前，报告保留区间或明确写出资料不足，而不以主观份额补齐。
""".strip()
    return {
        "entity_key": spec["key"],
        "section_key": "entity_research",
        "section_title": f"{name}：需求、竞争与验证重点",
        "body_markdown": body,
        "support_status": "partially_supported",
        "evidence_ref_uri_list": [source_uri(ref) for ref in refs],
    }


def _entity_section(spec: Mapping[str, Any], refs: list[str]) -> dict[str, Any]:
    """Write only the analysis unique to one equipment segment."""
    name = str(spec["name"])
    body = f"""
### 研究问题

{name}在2026—2030年是否会形成可见订单，关键不是项目名称，而是新增硅片产能是否需要这一工序、设备是否进入采购和验收，以及相关公司能否把合同转成收入。本页只研究{name}：{spec['description']}

### 证据和数据

当前最有区分力的事实是：{spec['focus']}。{_citation_text(refs[:5])} 历史合同只能证明厂商曾经具备产品或交付能力；2026—2030年的订单仍要由新项目合同、搬入、验收和回款确认。

### 分析

{spec['method']}。竞争上，{spec['competition']}。财务上，{spec['financial']}。因此，本页不把项目总投资、设备市场空间和供应商收入混为一项，也不把集团毛利率当作{name}项目的毛利率。

{ENTITY_UNIQUE_ANALYSIS[str(spec['key'])]}

### 项目金额怎样传到公司财务

{ENTITY_PROJECT_TO_FINANCIAL_BRIDGE[str(spec['key'])]}

### 结论

{ENTITY_CONCLUSIONS[str(spec['key'])]}

### 如果想进一步研究，需要补充的信息

需要补充{spec['follow_up']}。取得这些资料后，才能把本环节从产品与历史客户判断推进到工序金额、当期合同、验收、专题收入和经营现金流。
""".strip()
    cited_refs = _refs_from_markdown(body)
    return {
        "entity_key": spec["key"],
        "section_key": "entity_research",
        "section_title": f"{name}：需求、竞争与验证重点",
        "body_markdown": body,
        "support_status": "partially_supported",
        "evidence_ref_uri_list": [source_uri(ref) for ref in cited_refs],
    }


def _financial_target_map(
    payload: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    payload = payload or _load_json(FINANCIAL_DIR / "target_financials.json")
    return {target["target_id"]: target for target in payload["targets"]}


def _audited_financial_points(
    target: Mapping[str, Any],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return build_financial_data_points(
        target,
        sources_by_ref,
        normalize_order_intake_wording=True,
    )


TARGET_PRODUCT_EVIDENCE_REFS: dict[str, str] = {
    "pva_tepla": "FIN-PVA-02",
    "accretech": "FIN-ACC-03",
    "jingsheng": "FIN-JS-01",
    "kla": "S070",
}


def _build_target(
    *,
    target_id: str,
    entity_spec: Mapping[str, Any],
    financial_targets: Mapping[str, Mapping[str, Any]],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    index: int,
) -> dict[str, Any]:
    target = financial_targets[target_id]
    current_snapshot = current_snapshot_spec(target_id)
    text = TARGET_TEXT[target_id]
    ticker = str(target["ticker_verification"].get("requested_market_data_alias") or target["ticker_verification"]["official_code"])
    source_ref = TARGET_PRODUCT_EVIDENCE_REFS[target_id]
    source = sources_by_ref[source_ref]
    name = str(target["company_name_zh"])
    entity_name = str(entity_spec["name"])
    return {
        "entity_key": entity_spec["key"],
        "target_name": name,
        "ticker": ticker,
        "market": str(target["ticker_verification"].get("exchange") or "公开市场"),
        "target_type": "security",
        "target_url": source.get("url"),
        "exposure_rationale": f"{target['direct_relation']['summary_zh']} 在本实体中重点验证其与{entity_name}的直接关系。",
        "evidence_ref_uri": source_uri(source_ref),
        "research_action": f"按季度跟踪{name}与{entity_name}相关的具名订单、交付、验收、分部收入和现金回款，不用集团总收入替代专题收入。",
        "investment_view": text["view"],
        "risk_note": text["risk"],
        "target_priority": text["priority"],
        "target_quality_label": "直接产品或客户证据；三年以上财务与2026-07-17估值已补齐；专题订单仍待确认",
        "relative_preference": f"对{name}，先验证其在{entity_name}中的当前项目合同，再与同工序候选比较收入占比、验收和现金流兑现。",
        "confirmed_scenario_action": text["confirmed"],
        "falsified_scenario_action": text["falsified"],
        "target_profile_markdown": (
            f"{name}与{entity_name}存在直接或可核验的产品关系。{target['direct_relation']['summary_zh']}"
            f"研究不把{name}的业务相关性直接写成订单，当前最关键的确认点是{entity_spec['follow_up']}。"
        ),
        "target_deep_research_markdown": (
            f"对{name}的判断分成业务直接性、当前项目关系和财务穿透三步。{name}的业务直接性由发行人产品或历史合同确认；"
            f"{name}当前项目关系必须由2026—2030年的具名合同、交付或验收补齐；{name}的财务穿透要求分部订单、收入、毛利和经营现金流能够与{entity_name}对应。"
            f"{target['direct_relation']['caveat_zh']}因此，{name}的三年合并财务只用于检验公司经营承载力和周期位置，不作为硅片专用设备利润率。"
        ),
        "entity_relation_markdown": f"{name}用于检验{entity_name}能否从项目预算转化为供应商订单和收入。",
        "parent_research_relation_markdown": "该标的是设备侧研究中从项目、工序、供应关系到上市公司财务的最后一环。",
        "conditional_investment_recommendation": TARGET_CONDITIONAL_RECOMMENDATIONS[target_id],
        "financial_data_status": str(current_snapshot["financial_status"]),
        "link_status": "linked",
        "support_status": "partially_supported",
        "sort_order": index,
        "target_data_points": [
            *_audited_financial_points(target, sources_by_ref),
            _humanize_public_aliases(
                build_current_valuation_data_point(
                    target_id,
                    sources_by_ref=sources_by_ref,
                )
            ),
        ],
    }


def _build_basic_target(
    *,
    entity_key: str,
    target_name: str,
    ticker: str,
    source_ref: str,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    process: str,
    evidence: str,
    gap: str,
    index: int,
) -> dict[str, Any]:
    source = sources_by_ref[source_ref]
    translated = str(source.get("excerpt_zh") or source.get("excerpt") or "")
    point = {
        "metric_name": f"{target_name}的硅片设备直接证据",
        "metric_category": "product_and_customer_validation",
        "period": str(source.get("publish_date") or "截至研究日"),
        "unit": "事实",
        "value_text": evidence,
        "source_title": str(source.get("title") or source.get("title_zh") or ""),
        "source_publisher": str(source.get("publisher") or ""),
        "source_excerpt": str(source.get("excerpt") or translated),
        "evidence_ref_uri": source_uri(source_ref),
    }
    if str(source.get("language") or "").startswith("en"):
        point["source_title_zh"] = str(source.get("title_zh") or source.get("title") or "")
        point["source_excerpt_zh"] = translated
    return {
        "entity_key": entity_key,
        "target_name": target_name,
        "ticker": ticker,
        "market": "公开市场",
        "target_type": "security",
        "target_url": source.get("url"),
        "exposure_rationale": f"{target_name}与{process}有直接产品或客户证据；本轮只把这层关系作为研究入口。",
        "evidence_ref_uri": source_uri(source_ref),
        "research_action": f"跟踪{target_name}在2026—2030新增硅片项目中的具名合同、交付、验收和专题财务披露。",
        "investment_view": f"{evidence}。当前仍缺{gap}，因此不能把项目池金额直接写成公司收入。",
        "risk_note": f"如果{target_name}没有取得新增项目合同，或设备未通过量产验收，本主题对公司业绩的贡献可能很小。",
        "target_priority": "P1" if target_name == "晶升股份" else "P2",
        "target_quality_label": "直接产品或历史客户证据，当前订单待补",
        "relative_preference": f"只有在{target_name}的订单和验收证据强于同工序候选时，才上调研究优先级。",
        "confirmed_scenario_action": f"取得具名合同、设备搬入和验收，并能从财务中识别{process}收入时上调。",
        "falsified_scenario_action": "连续没有新增项目订单、客户改用其他供应商或最终验收失败时下调。",
        "target_profile_markdown": f"{target_name}对应{process}。{evidence}。这只证明产品或历史客户关系，不等于本轮新增订单。",
        "target_deep_research_markdown": f"研究重点是把产品能力、客户验证、当期合同和财务确认依次接通。当前缺口是{gap}，因此页面不展示没有证据支持的收入、毛利或估值结果。",
        "entity_relation_markdown": f"该标的用于验证{process}能否由国产或本土设备商承接。",
        "parent_research_relation_markdown": "该标的是设备侧研究中从项目、工序到供应商收入的验证对象。",
        "conditional_investment_recommendation": "当前只建议持续研究；具名订单、验收和专题收入同时出现后再评估盈利弹性。",
        "financial_data_status": "本轮未形成通过独立财务证据审计的三期专题财务序列，不以集团或相邻业务数据补齐。",
        "link_status": "linked",
        "support_status": "partially_supported",
        "sort_order": index,
        "target_data_points": [point],
    }


def _build_supplemental_financial_target(
    *,
    target_id: str,
    entity_key: str,
    product_source_ref: str,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    process: str,
    evidence: str,
    current_project_gap: str,
    priority: str,
    index: int,
) -> dict[str, Any]:
    spec = supplemental_financial_target_spec(target_id)
    decision = SUPPLEMENTAL_TARGET_DECISIONS[target_id]
    role_text = SUPPLEMENTAL_TARGET_ROLE_TEXT[target_id]
    name = str(spec["target_name"])
    product_source = sources_by_ref[product_source_ref]
    return {
        "entity_key": entity_key,
        "target_name": name,
        "ticker": str(spec["ticker"]),
        "market": str(spec["market"]),
        "target_type": "security",
        "target_url": product_source.get("url"),
        "exposure_rationale": f"{name}与{process}有直接产品或客户证据；财务序列用于检验经营承载力，不代替专题订单。",
        "evidence_ref_uri": source_uri(product_source_ref),
        "research_action": f"跟踪{name}在2026—2030新增硅片项目中的具名合同、交付、验收和{process}专题收入。",
        "investment_view": role_text["view"],
        "risk_note": decision["risk"],
        "target_priority": priority,
        "target_quality_label": "直接产品或客户证据；三年以上财务与当前估值已补齐；专题订单仍待确认",
        "relative_preference": f"先比较{name}与同工序候选的具名订单和验收，再比较财务承载力与当前估值，不按集团规模排序。",
        "confirmed_scenario_action": decision["confirmed"],
        "falsified_scenario_action": decision["falsified"],
        "target_profile_markdown": role_text["profile"],
        "target_deep_research_markdown": role_text["deep"],
        "entity_relation_markdown": f"该标的用于验证{process}需求能否转化为供应商订单、验收和收入。",
        "parent_research_relation_markdown": "该标的是设备侧研究中从项目、工序和供应关系到上市公司财务的验证对象。",
        "conditional_investment_recommendation": TARGET_CONDITIONAL_RECOMMENDATIONS[target_id],
        "financial_data_status": str(spec["financial_status"]),
        "link_status": "linked",
        "support_status": "partially_supported",
        "sort_order": index,
        "target_data_points": _humanize_public_aliases(
            build_supplemental_financial_points(
                target_id,
                product_source_ref=product_source_ref,
                product_evidence=evidence,
                sources_by_ref=sources_by_ref,
            )
        ),
    }


def _build_target_public_content_audit(pack: Mapping[str, Any]) -> dict[str, Any]:
    target_keys = {
        "PVA TePla": "pva_tepla",
        "东京精密／ACCRETECH": "accretech",
        "晶盛机电": "jingsheng",
        "KLA": "kla",
        "晶升股份": "crystal_rise",
        "Applied Materials": "applied_materials",
        "华海清科": "huahai_qingke",
    }
    required_terms = {
        "pva_tepla": ("新", "半导体硅片长晶", "2021年Siltronic"),
        "accretech": ("硅片", "研磨", "项目"),
        "jingsheng": ("半导体硅片专用设备", "光伏", "验证"),
        "kla": ("裸晶圆", "复购", "当前"),
        "crystal_rise": ("12英寸单晶炉", "恢复盈利", "验收"),
        "applied_materials": ("硅片外延", "腔体", "集团"),
        "huahai_qingke": ("大硅片", "复购", "专用毛利"),
    }
    fields = (
        "conditional_investment_recommendation",
        "risk_note",
        "confirmed_scenario_action",
        "falsified_scenario_action",
    )
    role_fields = (
        "target_profile_markdown",
        "target_deep_research_markdown",
        "investment_view",
    )
    failures: list[dict[str, str]] = []
    values_by_field: dict[str, list[str]] = {
        field: [] for field in (*fields, *role_fields)
    }
    role_sentence_occurrences: dict[str, list[dict[str, str]]] = {}
    role_overlap_failures: list[dict[str, Any]] = []
    targets = list(pack.get("entity_investment_targets") or [])
    for target in targets:
        name = str(target.get("target_name") or "")
        target_key = target_keys.get(name)
        if not target_key:
            failures.append({"target_name": name, "reason": "target_not_in_decision_registry"})
            continue
        combined = " ".join(str(target.get(field) or "") for field in fields)
        missing_terms = [term for term in required_terms[target_key] if term not in combined]
        if missing_terms:
            failures.append(
                {
                    "target_name": name,
                    "reason": f"missing_target_specific_terms:{missing_terms}",
                }
            )
        for field in (*fields, *role_fields):
            value = str(target.get(field) or "").strip()
            values_by_field[field].append(value)
            if len(value) < 30:
                failures.append({"target_name": name, "reason": f"{field}_too_short"})
        within_target: dict[str, set[str]] = {}
        for field in role_fields:
            value = str(target.get(field) or "")
            for sentence in re.split(r"[。！？；\n]+", value):
                normalized = re.sub(r"\s+", "", sentence).strip("，,：:；;。.")
                if len(normalized) < 20:
                    continue
                within_target.setdefault(normalized, set()).add(field)
                role_sentence_occurrences.setdefault(normalized, []).append(
                    {"target_name": name, "field": field}
                )
        for sentence, sentence_fields in within_target.items():
            if len(sentence_fields) > 1:
                role_overlap_failures.append(
                    {
                        "scope": "within_target",
                        "target_name": name,
                        "fields": sorted(sentence_fields),
                        "sentence": sentence,
                    }
                )
    for sentence, occurrences in role_sentence_occurrences.items():
        target_names = {row["target_name"] for row in occurrences}
        if len(target_names) > 1:
            role_overlap_failures.append(
                {
                    "scope": "across_targets",
                    "target_names": sorted(target_names),
                    "fields": sorted({row["field"] for row in occurrences}),
                    "sentence": sentence,
                }
            )
    for overlap in role_overlap_failures:
        failures.append(
            {
                "target_name": str(overlap.get("target_name") or "、".join(overlap.get("target_names") or [])),
                "reason": f"role_text_overlap:{overlap['scope']}:{overlap['sentence']}",
            }
        )
    duplicate_fields = [
        field
        for field, values in values_by_field.items()
        if len(values) != len(set(values))
    ]
    audit = {
        "audit_version": "equipment.target_public_content.v1",
        "as_of_date": AS_OF_DATE,
        "target_count": len(targets),
        "audited_target_count": len(targets) - sum(
            1 for failure in failures if failure["reason"] == "target_not_in_decision_registry"
        ),
        "duplicate_field_count": len(duplicate_fields),
        "duplicate_fields": duplicate_fields,
        "role_overlap_failure_count": len(role_overlap_failures),
        "role_overlap_failures": role_overlap_failures,
        "failures": failures,
        "status": "pass" if len(targets) == 7 and not failures and not duplicate_fields else "fail",
    }
    if audit["status"] != "pass":
        raise ValueError(f"设备标的公开内容审计失败：{audit}")
    return audit


def _build_critical_public_fact_citation_audit(
    pack: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove critical public rows cite the excerpt that contains their exact fact."""

    failures: list[dict[str, Any]] = []
    sources_by_ref = {
        str(source.get("ref") or ""): source for source in pack.get("sources") or []
    }
    visuals_by_key = {
        str(visual.get("block_key") or ""): visual for visual in pack.get("visuals") or []
    }

    source_requirements = {
        "S066": ("30万片/月", "334,614.10万元", "50万片/月", "678,768.03万元"),
        "S072": ("480万片", "601,905.00万元", "294,763.26万元", "48.97%"),
        "S073": ("180万片", "23.02亿元", "20.60%", "2027年12月"),
        "S074": ("180万片", "22.62亿元", "96万片", "12.30亿元"),
        "S075": ("5台化学机械抛光设备", "79%", "2台设备", "尚未完成合同验收"),
        "S076": ("3台研磨减薄设备", "尚未通过验收", "90%"),
        "S077": ("1.87亿元", "1.94亿元", "1.15亿元", "4.49亿元", "超过5亿元", "约3亿元"),
        "S078": ("300mm硅片二期项目", "67.10亿元", "2024年末", "30万片/月"),
        "S079": ("2015年", "上海新昇", "2018年度", "立昂微", "批量供应", "TCL中环"),
        "S080": ("2022.04.27", "研磨机", "2,937.60万美元", "正在履行"),
        "S081": ("Okamoto", "终端生产商", "直接合作"),
        "S082": ("710,733.24", "141,869.86", "567,596.55"),
        "FIN-PVA-06": ("156,624", "60,005", "37.7%", "37.3%"),
    }
    for ref, tokens in source_requirements.items():
        excerpt = str((sources_by_ref.get(ref) or {}).get("excerpt") or "")
        missing = [token for token in tokens if token not in excerpt]
        if missing:
            failures.append(
                {"scope": "source_excerpt", "ref": ref, "missing_tokens": missing}
            )

    def table_rows(block_key: str) -> list[list[Any]]:
        visual = visuals_by_key.get(block_key) or {}
        return list((visual.get("display_data") or {}).get("rows") or [])

    def audit_row(
        *,
        block_key: str,
        row_contains: Sequence[str],
        expected_refs: Sequence[str],
        row_tokens: Sequence[str],
        exact_refs: bool = True,
    ) -> None:
        matches = [
            row
            for row in table_rows(block_key)
            if all(token in " ".join(str(value) for value in row) for token in row_contains)
        ]
        if len(matches) != 1:
            failures.append(
                {
                    "scope": "public_table_row",
                    "block_key": block_key,
                    "row_contains": list(row_contains),
                    "reason": f"row_match_count:{len(matches)}",
                }
            )
            return
        row = matches[0]
        row_text = " ".join(str(value) for value in row)
        missing_row_tokens = [token for token in row_tokens if token not in row_text]
        actual_refs = _refs_from_markdown(str(row[-1]))
        ref_ok = (
            actual_refs == list(expected_refs)
            if exact_refs
            else all(ref in actual_refs for ref in expected_refs)
        )
        if missing_row_tokens or not ref_ok:
            failures.append(
                {
                    "scope": "public_table_row",
                    "block_key": block_key,
                    "row_contains": list(row_contains),
                    "missing_row_tokens": missing_row_tokens,
                    "expected_refs": list(expected_refs),
                    "actual_refs": actual_refs,
                }
            )

    project_block = "wafer_maker_equipment_project_database"
    audit_row(
        block_key=project_block,
        row_contains=("沪硅产业/上海新昇",),
        expected_refs=("S078", "S066"),
        row_tokens=("30万片/月", "2024年末", "67.1亿元"),
    )
    audit_row(
        block_key=project_block,
        row_contains=("奕斯伟材料", "武汉"),
        expected_refs=("S011", "S012", "S066"),
        row_tokens=("60万片/月", "125亿元", "66.9-81.5亿元"),
    )
    audit_row(
        block_key=project_block,
        row_contains=("上海超硅", "200毫米与300毫米硅片"),
        expected_refs=("S067", "S082", "S069", "S070", "S080", "S081", "S071"),
        row_tokens=("71.0733亿元", "75.18%"),
    )
    audit_row(
        block_key=project_block,
        row_contains=("立昂微", "12英寸全流程硅片"),
        expected_refs=("S072",),
        row_tokens=("40万片/月", "60.1905亿元", "29.4763亿元", "48.97%"),
    )
    audit_row(
        block_key=project_block,
        row_contains=("立昂微", "12英寸外延片"),
        expected_refs=("S073",),
        row_tokens=("15万片/月", "23.02亿元", "20.60%", "2027年12月"),
    )
    audit_row(
        block_key=project_block,
        row_contains=("立昂微", "12英寸轻掺外延片"),
        expected_refs=("S074",),
        row_tokens=("8万片/月", "12.3亿元"),
    )
    audit_row(
        block_key=project_block,
        row_contains=("立昂微", "12英寸重掺衬底片"),
        expected_refs=("S074",),
        row_tokens=("15万片/月", "22.62亿元"),
    )

    supplier_block = "wafer_maker_equipment_supplier_relationships"
    audit_row(
        block_key=supplier_block,
        row_contains=("西安奕材", "CMP/最终抛光"),
        expected_refs=("S075",),
        row_tokens=("5台", "2台", "最终合同验收"),
        exact_refs=False,
    )
    audit_row(
        block_key=supplier_block,
        row_contains=("上海新昇", "晶升股份"),
        expected_refs=("S079",),
        row_tokens=("2018年", "验收"),
    )
    audit_row(
        block_key=supplier_block,
        row_contains=("上海超硅", "常压外延", "Applied Materials"),
        expected_refs=("S069",),
        row_tokens=("2021年", "2022年"),
        exact_refs=False,
    )
    audit_row(
        block_key=supplier_block,
        row_contains=("上海超硅", "招股书匿名研磨设备供应商"),
        expected_refs=("S080",),
        row_tokens=("2937.6万美元", "不得自行具名"),
    )
    audit_row(
        block_key=supplier_block,
        row_contains=("上海超硅", "Okamoto"),
        expected_refs=("S081",),
        row_tokens=("具体机型", "本轮项目合同未披露"),
    )
    audit_row(
        block_key=supplier_block,
        row_contains=("西安奕材", "研磨减薄"),
        expected_refs=("S076",),
        row_tokens=("3台", "90%", "尚未验收"),
        exact_refs=False,
    )
    audit_row(
        block_key=supplier_block,
        row_contains=("西安奕材", "12英寸单晶生长"),
        expected_refs=("S077",),
        row_tokens=("在手合同", "意向合同"),
        exact_refs=False,
    )

    market_block = "equipment_market_space_results"
    audit_row(
        block_key=market_block,
        row_contains=("武汉60万片/月完整线完整建设",),
        expected_refs=("S066", "S011"),
        row_tokens=("66.9—81.5亿元",),
    )
    audit_row(
        block_key=market_block,
        row_contains=("当前可量化的四个中国项目",),
        expected_refs=("S066", "S068", "S072", "S073", "S011"),
        row_tokens=("66.9—146.4亿元", "立昂微两个代理上限"),
    )

    report_text = "\n".join(
        str(section.get("body_markdown") or "") for section in pack.get("sections") or []
    )
    required_report_refs = ("S072", "S073", "S074", "S075", "S076")
    missing_report_refs = [
        ref for ref in required_report_refs if f"^src:source_ref:{ref}" not in report_text
    ]
    stale_multifact_refs = [
        ref for ref in ("S003", "S005") if f"^src:source_ref:{ref}" in report_text
    ]
    if missing_report_refs or stale_multifact_refs:
        failures.append(
            {
                "scope": "main_report_fact_cluster_wiring",
                "missing_refs": missing_report_refs,
                "stale_multifact_refs": stale_multifact_refs,
            }
        )

    expected_target_refs = {
        "PVA TePla": "FIN-PVA-02",
        "东京精密／ACCRETECH": "FIN-ACC-03",
        "晶盛机电": "FIN-JS-01",
        "KLA": "S070",
        "晶升股份": "S079",
        "Applied Materials": "S069",
        "华海清科": "S033",
    }
    actual_target_refs = {
        str(target.get("target_name") or ""): str(target.get("evidence_ref_uri") or "").replace("source_ref:", "")
        for target in pack.get("entity_investment_targets") or []
    }
    target_ref_failures = {
        name: {"expected": expected_ref, "actual": actual_target_refs.get(name)}
        for name, expected_ref in expected_target_refs.items()
        if actual_target_refs.get(name) != expected_ref
    }
    if target_ref_failures:
        failures.append(
            {"scope": "target_top_level_evidence_refs", "failures": target_ref_failures}
        )

    entity_section_text = "\n".join(
        str(section.get("body_markdown") or "")
        for section in pack.get("entity_sections") or []
    )
    conclusion_missing = [
        key for key, conclusion in ENTITY_CONCLUSIONS.items() if conclusion not in entity_section_text
    ]
    if (
        conclusion_missing
        or len(ENTITY_CONCLUSIONS) != len(set(ENTITY_CONCLUSIONS.values()))
        or "的需求基础来自" in entity_section_text
    ):
        failures.append(
            {
                "scope": "entity_conclusions",
                "missing_entity_keys": conclusion_missing,
                "unique_conclusion_count": len(set(ENTITY_CONCLUSIONS.values())),
                "generic_template_present": "的需求基础来自" in entity_section_text,
            }
        )

    audit = {
        "audit_version": "equipment.critical_public_fact_citations.v1",
        "as_of_date": AS_OF_DATE,
        "critical_source_count": len(source_requirements),
        "audited_public_row_count": 16,
        "audited_target_ref_count": len(expected_target_refs),
        "main_report_required_fact_refs": list(required_report_refs),
        "failure_count": len(failures),
        "failures": failures,
        "status": "pass" if not failures else "fail",
    }
    if audit["status"] != "pass":
        raise ValueError(f"关键公开事实引用审计失败：{audit}")
    return audit


def _split_report() -> dict[str, str]:
    draft = (EQUIPMENT_DIR / "report_draft.md").read_text(encoding="utf-8")
    parts = re.split(r"(?m)^##\s+", draft)
    sections: dict[str, str] = {}
    for part in parts[1:]:
        title, body = part.split("\n", 1)
        sections[title.strip()] = natural_citations(body.strip())
    return sections


def _legacy_main_sections() -> list[dict[str, Any]]:
    draft = _split_report()
    section_1 = (
        draft["摘要"]
        + "\n\n### 项目证据怎样约束结论\n\n"
        + draft["设备需求首先取决于项目处在哪一步"]
        + "\n\n如果想进一步提高把握，最先需要补充的是武汉项目的正式采购公告和首批搬入清单；它们会把当前项目级估算替换为真实订单。"
    )
    section_2 = (
        "这一部分要回答的是：新增硅片产能究竟对应多少设备投入，以及这些投入何时可能成为设备商收入。\n\n"
        + draft["设备市场大约有多大"]
        + "\n\n### 计算与确认方法\n\n"
        "计算先使用两个已投产300毫米整线样本：沪硅产业30万片/月对应33.46亿元生产设备，西安奕材一厂设计50万片/月对应67.88亿元。"
        "由此得到每新增1万片/月约1.12—1.36亿元的公开样本区间，再乘武汉60万片/月，结果为66.9—81.5亿元。"
        "上海超硅外延项目使用其自身27.86亿元设备及安装预算，不套普通抛光片参数。采购时点按正式合同、交付、安装、转固、最终验收和收入确认分开；时间权重只分配金额，不改变设备数量或市场总额。"
        "这套方法的局限是项目配置、外延比例、进口设备价格、备机和厂务边界不同，因此结果是量级区间而非报价。"
        "^src:source_ref:S001 ^src:source_ref:S004 ^src:source_ref:S011\n\n"
        + draft["订单和收入确认风险"]
        + "\n\n如果想进一步研究，需要取得立昂微已下单未交付、已交付未验收和剩余设备预算的拆分，以及各设备商收入确认条款。"
    )
    section_3 = (
        "本节要回答哪些设备工序和供应商真正位于硅片制造链，而不是泛半导体设备概念。\n\n"
        + draft["哪些设备环节更可能受益"]
        + "\n\n### 供应关系如何分层\n\n"
        + draft["供应商受益排序"]
        + "\n\n判断方法是把每家公司依次放入三道筛选：产品是否明确用于硅衬底制造、是否存在量产客户或具名合同、是否与2026—2030新增项目直接相关。"
        "具名合同或量产交付优先于产品页面，产品页面优先于产业链推测；没有当前项目直接证据的公司可以作为竞争者跟踪，但不能用“可能受益”代替客户与订单。"
        "综合来看，可以认为直接产品和历史客户证据已经足以筛出重点候选，但尚不足以确认武汉等新增项目的供应份额。"
        "如果想进一步研究，需要补充武汉和立昂微的设备品牌、数量、合同金额与验收结果，并核对这些设备是否确实用于硅衬底而非器件晶圆加工。"
    )
    section_4 = (
        "本节要回答设备机会为何可能不兑现，以及怎样把项目级市场空间转成上市公司的盈利判断。\n\n"
        + draft["哪些情况会让设备机会低于预期"]
        + "\n\n### 上市公司财务怎样使用\n\n"
        "晶盛机电、东京精密、PVA TePla和KLA均取得了至少三期发行人财务，但它们的合并报表都不等于硅片专用设备业务。"
        "晶盛机电2025年合并收入较2024年明显回落，说明光伏等其他业务会掩盖硅片设备增量；东京精密、KLA的半导体设备覆盖更广；PVA TePla的半导体系统也包含其他应用。"
        "因此，财务分析只把集团收入、利润和经营现金流作为承载力与周期检查，真正的盈利弹性必须等硅片专用订单或分部披露后再算。"
        "敏感性可以直接说明：武汉设备预算每变动10%，项目级金额约变动6.7—8.1亿元；但在供应商份额公开前，这一变化不能继续乘集团毛利率得到净利润。"
        "^src:source_ref:FIN-JS-01 ^src:source_ref:FIN-ACC-01 ^src:source_ref:FIN-PVA-01 ^src:source_ref:FIN-KLA-01\n\n"
        "### 综合判断\n\n"
        + draft["结论"]
        + "\n\n### 如果想进一步研究，需要补充的信息\n\n"
        + draft["如果想进一步研究，需要补充的信息"]
    )
    definitions = (
        ("summary", "摘要", section_1, ["S001", "S004", "S005", "S011", "S014", "S017", "S020", "S027"]),
        ("market_model", "扩产怎样转化为设备订单", section_2, ["S001", "S003", "S004", "S005", "S011"]),
        ("equipment_competition", "哪些设备和供应商真正受益", section_3, ["S075", "S069", "S028", "S079", "S031", "S070", "S036", "S038"]),
        ("investment_risk", "上市公司机会、风险与验证", section_4, ["S004", "S005", "S014", "S018", "S027", "FIN-JS-01", "FIN-ACC-01", "FIN-PVA-01", "FIN-KLA-01"]),
    )
    return [
        {
            "section_key": key,
            "section_title": title,
            "body_markdown": body,
            "support_status": "partially_supported",
            "evidence_ref_uri_list": [source_uri(ref) for ref in refs],
        }
        for key, title, body, refs in definitions
    ]


def _main_sections() -> list[dict[str, Any]]:
    summary = """
本研究要回答的是：2026—2030年硅片厂扩产会形成多少制造设备需求，哪些厂商有能力承接，哪些只是泛半导体设备概念。

现有一手资料不足以量化全球设备市场，武汉项目也不能冒充全球下限。在武汉60万片/月300毫米完整线按当前计划完整建设的条件下，按两个已投产中国样本反推生产设备投入约66.9—81.5亿元；把武汉高样本、立昂微两个未完成项目的代理上限和上海超硅规划设备预算纳入后，当前四个可量化中国项目的条件情景为66.9—146.4亿元。146.4亿元不包含其他未披露设备预算的中国和海外项目，因此不是中国全部已识别项目的上限。这个区间是条件项目设备金额，不是订单、收入或利润。^src:source_ref:S066 ^src:source_ref:S068 ^src:source_ref:S072 ^src:source_ref:S073 ^src:source_ref:S011

中国设备商可服务金额只能做敏感性。窄覆盖假设为工序覆盖25%×目标规格合格50%×窗口内采购兑现75%，对应6.3—13.7亿元；中等覆盖假设为40%×70%×85%，对应15.9—34.8亿元；宽覆盖压力测试为60%×90%×100%，对应36.1—79.1亿元。三档比例都是研究假设，不是公开国产化率。单家公司金额必须从选定的可服务金额继续计算，不能跳回未经筛选的四项目金额；例如中等覆盖敏感性下，1%、5%和10%综合份额分别对应0.16—0.35亿元、0.80—1.74亿元和1.59—3.48亿元。这仍是金额敏感性，不是份额、订单或收入预测。

供应商证据排序显示，晶盛机电、晶升股份、KLA、应用材料和PVA TePla具有较直接的产品、客户或历史合同证据；华海清科、北方华创、中科飞测和东京精密产品匹配但本轮项目订单不足；芯源微、Lam Research和Tokyo Electron等不能只因属于半导体设备行业就列为硅片制造设备受益者。^src:source_ref:S028 ^src:source_ref:S079 ^src:source_ref:S070 ^src:source_ref:S036 ^src:source_ref:S042 ^src:source_ref:S050 ^src:source_ref:S053

因此，当前最有用的结论不是给出一项伪精确的全球市场规模，而是把项目、工序和供应商逐层筛选：先跟踪武汉设备搬入和合同，再核验立昂微与上海超硅的实际开工和采购，最后等待设备商的具名订单、验收与专题收入。海外项目多数已过资本开支高峰，不能把历史总投资重新计入2026—2030需求。^src:source_ref:S017 ^src:source_ref:S018 ^src:source_ref:S020 ^src:source_ref:S021
""".strip()

    demand_chain = """
本节要回答的是：先进逻辑、存储、功率和SOI需求怎样变成硅片制造设备订单。下游扩产不会自动变成硅片设备订单，传导必须依次经过“晶圆厂新增开工量—硅片采购—硅片厂新增有效产能—设备合同—交付验收—设备商收入”，任何一环只停留在规划都应折扣。

先进逻辑和AI项目增加300毫米高规格抛光片需求，并可能提高退火、外延和裸片检测要求；台积电新增晶圆厂计划证明方向，但其1,650亿美元美国投资还包含封装和研发，不能直接换成硅片需求。^src:source_ref:S055 DRAM与HBM项目也主要拉动300毫米存储用抛光片；美光和SK海力士的项目说明需求方向与投产进度，但没有公开同口径新增月产能（片/月），HBM堆叠层数更不能重复乘入晶圆开工量。^src:source_ref:S056 ^src:source_ref:S057 ^src:source_ref:S058

NAND要单独处理。铠侠明确优先使用既有Y7、K2洁净室，并把新厂房放到2029年以后视市场决定，因此位需求增长并不必然增加同等硅片面积，更不必然需要一条新硅片完整线。^src:source_ref:S059 中国存储扩产方向由长江存储三期和长鑫在建资产支持，但公开资料没有可比月产能和硅片采购合同，只能作为300毫米国产硅片的潜在需求方向。^src:source_ref:S060 ^src:source_ref:S061

功率半导体更偏向200毫米或300毫米重掺衬底、外延片，设备价值向重掺长晶、外延和外延后检测倾斜；英飞凌300毫米智能功率厂和立昂微衬底/外延项目支持这一方向。^src:source_ref:S062 ^src:source_ref:S074 射频与汽车电子则把需求延伸到SOI专有工序。SOI在普通抛光片后增加氧化、离子注入、键合、高温退火剥离、减薄、终洗和专用量测，不能套普通300毫米整线强度。^src:source_ref:S004 ^src:source_ref:S063

根据现有证据，可以认为先进逻辑、DRAM/HBM、功率和SOI会拉动不同设备组合，NAND则需要更谨慎。若要把这些方向变成设备数量，还需逐项目取得新增月产能（片/月）、硅片规格、客户认证、工序配置、设备综合效率和备机率。
""".strip()

    historical_cycle = """
### 2020年以来的硅片周期、本土扩产与设备国产化

回看历史是为了判断2026—2030年的项目会不会重演上一轮扩产，而不是把旧合同重新算成未来订单。SEMI数据显示，全球半导体硅晶圆出货面积从2020年的12,407百万平方英寸升至2022年的14,713百万平方英寸，销售额同期从112亿美元升至138亿美元；2023年出货回落到12,602百万平方英寸、销售额降至123亿美元，2024年又降到12,266百万平方英寸和115亿美元。也就是说，2020—2022年是量价共同向上的扩张阶段，2023—2024年则进入库存调整和利用率下降阶段。SEMI只观察到2024年下半年开始复苏，尚不足以证明新一轮全面扩产已经启动。^src:source_ref:S065

这组硅晶圆数据只反映半导体周期的衬底端，不能替代全球芯片销售、晶圆厂利用率和资本开支的完整历史序列；本轮公开资料没有形成三者在2020—2025年的统一可比口径，因此不把它写成整个半导体行业的精确周期。现有晶圆厂证据仍能看出本轮复苏的结构差异：台积电美国计划集中于先进逻辑并配套先进封装，美光和SK海力士扩产指向DRAM/HBM，英飞凌新增300毫米功率产能；相对地，铠侠优先在既有洁净室安装设备，并把新厂房放到2029年以后视市场决定。^src:source_ref:S055 ^src:source_ref:S056 ^src:source_ref:S058 ^src:source_ref:S059 ^src:source_ref:S062 因而，下游晶圆厂并非同步扩产，AI、先进逻辑和HBM强于多数成熟终端；只有新晶圆投入真正增加并传导到硅片采购，才会形成硅片厂扩产需求。

上一轮上行期确实形成了设备采购。PVA TePla在2021年获得Siltronic价值9,500万欧元的长晶系统订单；上海超硅在2021—2022年签署应用材料外延系统、研磨机和KLA晶圆几何量测设备合同。国内厂商也从产品开发进入产线导入：西安奕材在2021—2024年采购浙江芯晖装备的5台CMP设备和3台研磨减薄设备，5台CMP设备已经转为固定资产，但其中2台尚未完成最终合同验收；3台研磨减薄设备已支付90%，却仍因光滑度参数稳定性不足而未验收、未转固。^src:source_ref:FIN-PVA-02 ^src:source_ref:S069 ^src:source_ref:S070 ^src:source_ref:S071 ^src:source_ref:S075 ^src:source_ref:S076 这说明国产化不是一个统一比例：同一家硅片厂内，长晶、CMP、研磨、外延和检测可以处在完全不同的验证阶段，采购、投入使用和最终验收也不是同一件事。

中国硅片产业本身也在扩产和分品类发展。西安奕材披露2024年末300毫米硅片产能约71万片/月，并把2026年目标定在120万片/月；上海超硅300毫米线的瓶颈年产能在2023—2025年持续增加；立昂微则同时布局300毫米抛光片、重掺衬底和外延片。^src:source_ref:S013 ^src:source_ref:S067 ^src:source_ref:S072 ^src:source_ref:S073 ^src:source_ref:S074 这些里程碑说明国产硅片已经从单一规划走向规模产能和差异化产品，但设计产能、瓶颈产能、实际产量和合格客户需求仍是四个不同口径。国产硅片扩产会为国产设备提供验证场景，却不会自动变成国产设备订单；是否复购、能否通过目标规格验证以及最终验收，才决定国产化能否从单台导入走向批量替代。

2023年后的供需错位解释了为什么新增产能不能直接换成新增设备。上海超硅300毫米线按瓶颈设备计算的年产能从2023年的133.57万片增至2025年的367万片，但同期平均售价从每片385.97元降至322.57元，2025年产能利用率只有75.18%。^src:source_ref:S067 海外扩产也从建设转向消化：环球晶圆称资本开支高峰已过、重点转向爬坡和客户验证；世创电子资本开支从2024年的5.234亿欧元降至2025年的3.69亿欧元；Soitec对2026财年的资本开支指引同样低于2025财年。^src:source_ref:S018 ^src:source_ref:S021 ^src:source_ref:S026

2025年的数据进一步显示，这是“出货先恢复、价格仍承压”的复苏：全球硅晶圆出货面积增长5.8%，销售额却下降1.2%。^src:source_ref:S027 因此，2026—2030年与2020—2022年最大的区别，是当前同时存在三类项目：武汉60万片/月项目属于尚待设备搬入的新完整线；环球晶圆、SK Siltron和世创电子等项目主要处在验证或爬坡期；SUMCO的大部分新增晶圆加工能力又延后到2031年。^src:source_ref:S011 ^src:source_ref:S014 ^src:source_ref:S018 ^src:source_ref:S021 ^src:source_ref:S023 未来设备需求更可能按项目、工序和验收节点分化，而不是所有硅片厂同步扩张。

根据这些历史证据，可以认为本轮机会的核心不是简单复制上一轮资本开支，而是寻找“价格和利用率企稳、项目资金落实、设备合同具名、交付验收完成”同时出现的项目。若要进一步判断周期斜率，还需补充主要硅片厂按尺寸和品类划分的季度利用率、平均售价、库存、2026—2030年剩余设备预算，以及国产设备在每道工序的复购和最终验收记录。
""".strip()

    project_analysis = """
本轮项目库覆盖23项硅片项目或负面检索记录。项目价值不由数量决定：武汉项目同时披露60万片/月、125亿元总投资和2026年四季度设备搬入，是未来设备需求最直接的量化锚；立昂微40万片/月完整线预算60.1905亿元、截至2025年末累计投入29.476326亿元、工程进度48.97%，其180万片/年外延项目工程进度20.60%并延期至2027年12月，说明尚未发生的设备额只能形成上限；上海超硅薄层外延项目直接披露27.86亿元设备及安装预算，但仍处规划阶段。^src:source_ref:S011 ^src:source_ref:S072 ^src:source_ref:S073 ^src:source_ref:S068

海外项目的处理更加保守。SUMCO修订方案把主要晶圆加工能力放到2031年，只有部分晶体能力处于本研究窗口；环球晶圆得州、密苏里和世创电子新加坡项目已经投入大量资本，2026年重点转向爬坡、送样和客户验证；Soitec新加坡厂房仍可随需求安装工具，但没有披露尚未安装设备的金额。因此这些项目证明设备种类、项目阶段和上行触发器，却不能把历史总投资再次加入未来市场。^src:source_ref:S014 ^src:source_ref:S017 ^src:source_ref:S018 ^src:source_ref:S019 ^src:source_ref:S020 ^src:source_ref:S021 ^src:source_ref:S046

点名对象也要保留负面结论。本轮没有找到由信越化学、监管或政府文件确认的2026—2030新增半导体硅片制造项目；已找到的伊势崎830亿日元项目是光刻材料基地，已经排除。^src:source_ref:S045 市场传闻项目没有可核验来源，不进入金额测算；中环领先35/60/70万片/月口径冲突，神工股份相关募投又已终止，都只保留跟踪或反方作用。^src:source_ref:S007 ^src:source_ref:S008 ^src:source_ref:S009 ^src:source_ref:S049

结论是，23项台账可以支持项目筛选和阶段判断，但只有少数项目能够进入金额模型。如果想扩大可计算范围，需要补充每个海外项目在2026—2030年尚未发生的设备资本开支、设备拆分和合同时间表。
""".strip()

    market_model = """
市场空间分四层计算，避免把全球需求、中国项目池、国产厂商可服务金额和公司收入混成一个数字。

> **核心计算关系**
>
> 项目设备需求 = 新增有效月产能 × 同类已投产整线的单位产能生产设备投入
>
> 中国设备商可服务金额 = 四项目条件设备金额 × 国产产品覆盖工序比例 × 目标规格合格比例 × 窗口内采购兑现比例
>
> 单家公司可获得金额 = 中国设备商可服务金额 × 假设综合份额

这三步分别回答项目需要多少设备、其中多少可能由中国设备商服务、以及单家公司在假设份额下对应多少金额。后一层只能承接前一层经过筛选的结果，不能直接把项目总投资乘公司份额。

第一层是项目设备需求。武汉采用“新增有效月产能×同类已投产整线的单位产能生产设备投入”：沪硅产业30万片/月对应33.46141亿元生产设备，西安奕材50万片/月设计产能对应67.876803亿元，得到每新增1万片/月约1.12—1.36亿元；乘武汉60万片/月，结果为66.9—81.5亿元。^src:source_ref:S066 ^src:source_ref:S011 外延项目不用这组参数，直接使用上海超硅披露的27.856575亿元设备及安装预算；立昂微完整线未完成部分按60.1905亿元总预算减去29.476326亿元累计投入，再乘可比完整线设备占比形成代理上限；立昂微外延项目以23.02亿元预算和20.60%工程进度估算剩余预算，但工程进度不等于设备采购进度。^src:source_ref:S068 ^src:source_ref:S072 ^src:source_ref:S073

第二层是全球设备需求。现有一手资料不能量化全球金额：SUMCO、Soitec、环球晶圆、世创电子和SK Siltron均缺少同口径的剩余设备支出、采购节奏或设备拆分；武汉66.9—81.5亿元只在该项目按60万片/月完整建设时成立，不能当作全球下限。^src:source_ref:S014 ^src:source_ref:S018 ^src:source_ref:S021 ^src:source_ref:S023 ^src:source_ref:S046

第三层是中国厂商可服务金额。计算为“四项目条件金额×国产产品覆盖工序比例×目标规格合格比例×窗口内采购兑现比例”。三档比例全部是研究假设，用来显示结论对覆盖、认证和时点的敏感性；没有一档被当作最可能值。第四层才是公司金额换算，且必须使用第三层选定的可服务金额再乘假设综合份额。窄覆盖、中等覆盖和宽覆盖三档下，1%份额分别对应0.06—0.14亿元、0.16—0.35亿元和0.36—0.79亿元；10%份额分别对应0.63—1.37亿元、1.59—3.48亿元和3.61—7.91亿元。这样可避免把未经工序覆盖、规格合格和采购兑现筛选的项目金额直接分给公司；结果仍不是任何公司的真实份额、订单或收入预测。

如果想进一步研究，需要补充海外项目剩余设备资本开支、中国项目设备分工与招标、目标规格合格清单、工序价值占比、供应商中标金额、验收条款和收入确认节奏，才能分别估算全球设备需求、中国厂商可服务空间和单家公司可获得空间。集团毛利率不能乘这些项目金额推算项目利润。
""".strip()

    suppliers = """
供应商筛选采用三道证据门槛：产品必须明确用于硅衬底制造；其次要有量产客户、合同、交付或验收；最后才核验它是否与2026—2030新增项目相关。本轮共筛查27家点名或延伸候选；浙江芯晖装备与西安芯晖设备按两个独立法人分列。其中22家至少有可点击的一手产品、客户或边界材料，进入公开筛选表；精测电子、沈阳科仪、Lam Research、Tokyo Electron和一项无法唯一识别的日本设备候选没有找到可唯一映射到硅衬底制造的一手产品或客户材料，只在正文披露检索限制，不占用要求逐行核验的公开表格。10家上市公司另按证据验证优先级比较；排序表示先研究谁，不是收益率预测或买入建议。

晶盛机电和晶升股份在长晶环节的国内证据最强。晶盛机电产品覆盖更广，但集团收入受光伏业务影响；晶升股份已补齐2023—2025年财务和2026-07-14估值，2025年收入、毛利率明显下降并转亏，说明业务更直接不等于当期盈利更稳。KLA和应用材料有上海超硅具名合同，PVA TePla有Siltronic历史订单和可穿透的半导体系统分部信息。^src:source_ref:S069 ^src:source_ref:S070 ^src:source_ref:S028 ^src:source_ref:S029 ^src:source_ref:S079 ^src:source_ref:S036 ^src:source_ref:S042 ^src:source_ref:FIN-PVA-02 ^src:source_ref:FIN-PVA-06 ^src:source_ref:FIN-EQ-JS-ANNUAL ^src:source_ref:FIN-EQ-JS-MARKET

华海清科、北方华创和中科飞测代表国产替代的上行空间，但目前主要是产品、匿名验证或应用证据，目标项目客户和复购不足。东京精密产品边界直接，当前项目订单仍不可得。^src:source_ref:S031 ^src:source_ref:S033 ^src:source_ref:S038 ^src:source_ref:S051 ^src:source_ref:S050 芯源微则已有可核验材料表明其相关清洗产品服务器件晶圆工序，而不是硅衬底终洗，因此不进入核心受益排序。^src:source_ref:S053 上述另外五家没有直接证据的结论来自本轮负面检索，而不是S053或其他单一来源；公开资料不足时，本研究不为它们补写产品、客户或供应关系。

公司财务只回答经营承载力和周期位置，不能替代硅片专用收入。晶盛机电FY2025集团毛利率28.88%、KLA FY2025集团毛利率60.91%、东京精密FY2025/03集团毛利率41.49%都不是硅片项目毛利率；PVA TePla FY2025半导体系统外部收入1.566亿欧元、分部毛利润0.600亿欧元，年报披露毛利率37.7%，其分母为包含内部收入的分部总收入，且该分部仍包含非硅片应用。^src:source_ref:FIN-JS-01 ^src:source_ref:FIN-KLA-01 ^src:source_ref:FIN-ACC-01 ^src:source_ref:FIN-PVA-06

四个原先缺少当前估值的标的已用允许的数据源补齐到2026-07-17：晶盛机电、PVA TePla、东京精密和KLA的PE、PB、PS、市值、ROE、ROA、EPS与BPS都在下表按各自币种和报告期展示。KLA的人民币市值使用本次同批USDCNY快照折算；与旧缓存的微小差异只反映汇率口径，不能解释成经营变化。估值快照不会提高供应关系等级，也不能替代硅片专用订单和分部利润。^src:source_ref:FIN-EQ-JINGSHENG-MARKET ^src:source_ref:FIN-EQ-PVA-MARKET ^src:source_ref:FIN-EQ-ACCRETECH-MARKET ^src:source_ref:FIN-EQ-KLA-MARKET

根据现有证据，最先应该验证武汉的单晶炉、研磨抛光、终洗和检测清单，其次验证立昂微与上海超硅的外延合同。若项目延期、硅片厂先提高既有设备利用率、国产设备终验失败，或海外项目继续只做爬坡而不新增工具，设备需求会显著低于项目总投资暗示的空间。如果想进一步研究，需要补充具名中标、合同金额、交付/初验/终验节点、硅片设备专题收入和现金回款。
""".strip()

    supplier_addendum = """
### 怎样使用排序和持续跟踪

十家公司排序只反映证据验证优先级：有具名合同、历史量产客户和专题财务的公司排在前面，只有产品匹配或匿名验证的公司排在观察层。它没有使用股价、估值或主观收益率，也没有把集团毛利率当作硅片设备盈利。实际更新时，先登记硅片厂项目的新增有效产能、产品规格和工序清单，再记录设备招标、合同、交付、初验、终验、收入与回款；任何供应关系都必须回到同一项目和同一设备工序。

如果只有项目开工而没有设备清单，结论停留在市场需求；如果只有设备商产品页而没有客户，结论停留在候选；只有具名订单和验收同时出现，才能进入供应商收入判断。这个更新方法可以防止把海外历史合同、中国规划产能和设备商集团收入混在一起，也能及时识别项目取消、采购后移、验收失败或进口设备继续占据关键工序等反方变化。
""".strip()
    return [
        _report_section(
            section_key="summary",
            section_title="摘要",
            body_markdown=summary + "\n\n### 项目证据怎样约束结论\n\n" + project_analysis,
        ),
        _report_section(
            section_key="demand_and_market_model",
            section_title="下游扩产怎样传导到设备需求和市场空间",
            body_markdown=(
                demand_chain
                + "\n\n"
                + historical_cycle
                + "\n\n### 市场空间怎样计算\n\n"
                + market_model
            ),
        ),
        _report_section(
            section_key="supplier_analysis",
            section_title="供应商格局、上市公司排序与风险",
            body_markdown=suppliers + "\n\n" + supplier_addendum,
        ),
    ]


def _model_bundle(output_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    intensity_samples = [
        {
            "project_name": "沪硅产业300毫米二期",
            "incremental_wspm": 300_000,
            "production_equipment_rmb_100m": 33.46141,
            "source_refs": ["S066"],
        },
        {
            "project_name": "西安奕材一厂设计口径",
            "incremental_wspm": 500_000,
            "production_equipment_rmb_100m": 67.876803,
            "source_refs": ["S066"],
        },
    ]
    sample_intensities = [
        float(row["production_equipment_rmb_100m"])
        * 100_000_000
        / (float(row["incremental_wspm"]) * 12)
        for row in intensity_samples
    ]
    intensity_low = min(sample_intensities)
    intensity_high = max(sample_intensities)
    intensity_base = (intensity_low + intensity_high) / 2
    inputs: dict[str, Any] = {
        "years": [2026, 2027, 2028, 2029, 2030],
        "semi_msi": {"scenarios": {}},
        "fab_projects": [],
        "wafer_capacity_projects": [
            {
                "project_name": "奕斯伟武汉300毫米完整线",
                "process_type": "300毫米完整抛光片生产线",
                "incremental_wspm": 600_000,
                "conditional_execution_switch": 1,
                "source_refs": ["S011"],
                "classification": "条件情景开关，非发生概率",
                "formula": "若武汉项目按60万片/月完整建设，则开关=1；若该条件不成立，则本情景不适用。",
            }
        ],
        "equipment_intensity_by_process": {
            "300毫米完整抛光片生产线": {
                "low": intensity_low,
                "base": intensity_base,
                "high": intensity_high,
                "source_refs": ["S066"],
                "classification": "两个已投产中国完整线样本的单位年产能生产设备投入",
                "formula": "生产设备投入÷（设计月产能×12）；低/高取两个样本端点，中值取两端算术平均。",
            }
        },
        "equipment_intensity_samples": [
            {
                **row,
                "intensity_rmb_per_annual_wafer": sample_intensities[index],
                "classification": "外部披露值经公式换算",
                "formula": "生产设备投入（元）÷（设计月产能×12）",
            }
            for index, row in enumerate(intensity_samples)
        ],
        "direct_budget_projects": [
            {
                "project_name": "上海超硅300毫米薄层外延项目",
                "equipment_and_installation_rmb_100m": 27.856575,
                "status": "规划阶段",
                "base_case_inclusion": False,
                "source_refs": ["S068"],
                "classification": "发行人规划预算；仅进入条件高情景",
                "formula": "直接使用披露的设备购置及安装工程费，不乘执行概率。",
            }
        ],
        "equipment_scenario_assumptions": {
            "wuhan_total_project_rmb_100m": 125.0,
            "leon_full_line_total_budget_rmb_100m": 60.1905,
            "leon_full_line_cumulative_input_rmb_100m": 29.476326,
            "leon_epi_total_budget_rmb_100m": 23.02,
            "leon_epi_engineering_progress_ratio": 0.206,
            "shanghai_epi_total_budget_rmb_100m": 29.808196,
            "shanghai_epi_equipment_installation_rmb_100m": 27.856575,
            "limitations": (
                "立昂微工程进度不等于设备采购或财务进度；用剩余总预算和可比项目设备占比只能形成情景上限。"
                "公开资料不足以把尚未发生的设备投入精确分配到年度，因此不输出年度订单或安装金额。"
            ),
        },
        "model_input_provenance": {
            "wuhan_total_project_rmb_100m": {"source_refs": ["S011"], "classification": "外部披露项目总投资", "formula": "直接取披露值125亿元"},
            "leon_full_line_total_budget_rmb_100m": {"source_refs": ["S072"], "classification": "外部披露项目总投资", "formula": "601,905.00万元÷10,000=60.1905亿元"},
            "leon_full_line_cumulative_input_rmb_100m": {"source_refs": ["S072"], "classification": "外部披露累计投入", "formula": "294,763.26万元÷10,000=29.476326亿元"},
            "leon_epi_total_budget_rmb_100m": {"source_refs": ["S073"], "classification": "外部披露项目预算", "formula": "直接取披露值23.02亿元"},
            "leon_epi_engineering_progress_ratio": {"source_refs": ["S073"], "classification": "外部披露工程进度；仅作预算代理", "formula": "20.60%写为0.206，不解释为设备采购进度"},
            "shanghai_epi_total_budget_rmb_100m": {"source_refs": ["S068"], "classification": "外部披露项目预算", "formula": "298,081.96万元÷10,000=29.808196亿元"},
            "shanghai_epi_equipment_installation_rmb_100m": {"source_refs": ["S068"], "classification": "外部披露设备及安装预算", "formula": "278,565.75万元÷10,000=27.856575亿元"},
            "china_sam_sensitivity_assumptions": {"source_refs": [], "classification": "研究敏感性假设，非外部事实", "formula": "条件项目金额×工序覆盖率×规格合格率×窗口采购兑现率"},
            "company_combined_share_sensitivity": {"source_refs": [], "classification": "研究敏感性假设，非外部事实", "formula": "选定的可服务金额×假设综合份额"},
        },
        "china_sam_sensitivity_assumptions": [
            {
                "scenario": "窄覆盖情景",
                "domestic_process_coverage": 0.25,
                "specification_qualification": 0.50,
                "window_procurement_realization": 0.75,
                "classification": "研究假设，非外部事实",
            },
            {
                "scenario": "中等覆盖敏感性",
                "domestic_process_coverage": 0.40,
                "specification_qualification": 0.70,
                "window_procurement_realization": 0.85,
                "classification": "研究假设，非外部事实",
            },
            {
                "scenario": "宽覆盖压力测试",
                "domestic_process_coverage": 0.60,
                "specification_qualification": 0.90,
                "window_procurement_realization": 1.00,
                "classification": "研究假设，非外部事实",
            },
        ],
        "company_combined_share_sensitivity": [0.01, 0.03, 0.05, 0.10],
        "boundaries": {
            "market_definition": "半导体硅片制造设备，不含芯片晶圆厂通用光刻、刻蚀和薄膜设备",
            "scenario_scope": "武汉完整建设时形成66.9—81.5亿元条件区间；四个可量化项目的高情景为146.4亿元，不代表中国全部已识别项目上限",
            "sam_som": "国产覆盖、规格合格、采购兑现与公司综合份额均未公开；只输出研究假设敏感性和金额换算，不把任何一档写成预测",
        },
    }
    outputs = build_model_outputs(inputs)
    outputs.pop("semi_area_scenarios", None)
    outputs.pop("project_demand", None)
    wuhan = outputs["equipment_project_pool"][0]
    assumptions = inputs["equipment_scenario_assumptions"]
    wuhan_budget = wuhan["equipment_budget_rmb_100m"]
    wuhan_share_low = wuhan_budget["low"] / assumptions["wuhan_total_project_rmb_100m"]
    wuhan_share_high = wuhan_budget["high"] / assumptions["wuhan_total_project_rmb_100m"]
    leon_full_remaining = (
        assumptions["leon_full_line_total_budget_rmb_100m"]
        - assumptions["leon_full_line_cumulative_input_rmb_100m"]
    )
    leon_epi_remaining_proxy = assumptions["leon_epi_total_budget_rmb_100m"] * (
        1 - assumptions["leon_epi_engineering_progress_ratio"]
    )
    epi_equipment_share = (
        assumptions["shanghai_epi_equipment_installation_rmb_100m"]
        / assumptions["shanghai_epi_total_budget_rmb_100m"]
    )
    component_ranges = [
        {
            "project_name": "奕斯伟武汉300毫米完整线",
            "low_rmb_100m": wuhan_budget["low"],
            "high_rmb_100m": wuhan_budget["high"],
            "evidence_type": "用两条已投产300毫米完整线的单位产能设备投入反推",
            "current_status": "主体封顶，计划2026年四季度设备搬入",
            "source_refs": ["S066", "S011"],
            "inclusion_scope": "项目按60万片/月完整建设的条件情景",
        },
        {
            "project_name": "立昂微40万片/月完整线未完成部分",
            "low_rmb_100m": leon_full_remaining * wuhan_share_low,
            "high_rmb_100m": leon_full_remaining * wuhan_share_high,
            "evidence_type": "剩余总预算乘武汉完整线设备占比，仅作可比项目代理",
            "current_status": "截至2025年末工程进度48.97%，已采购部分未公开",
            "source_refs": ["S072"],
            "inclusion_scope": "仅进入四项目高情景；不进入条件低情景",
        },
        {
            "project_name": "立昂微180万片/年外延项目未完成部分",
            "low_rmb_100m": 0.0,
            "high_rmb_100m": leon_epi_remaining_proxy * epi_equipment_share,
            "evidence_type": "剩余项目预算乘上海超硅外延项目设备占比，只形成上限",
            "current_status": "截至2025年末工程进度20.60%，项目延期至2027年底",
            "source_refs": ["S068", "S073"],
            "inclusion_scope": "仅进入四项目高情景；工程进度不是设备采购进度",
        },
        {
            "project_name": "上海超硅180万片/年薄层外延项目",
            "low_rmb_100m": 0.0,
            "high_rmb_100m": assumptions["shanghai_epi_equipment_installation_rmb_100m"],
            "evidence_type": "发行人直接披露设备及安装预算，融资和开工前仍为条件项目",
            "current_status": "募投规划阶段，披露建设期24个月",
            "source_refs": ["S068"],
            "inclusion_scope": "仅进入四项目高情景；规划预算不是订单",
        },
    ]
    wuhan_conditional_low = float(wuhan_budget["low"])
    wuhan_conditional_high = float(wuhan_budget["high"])
    four_project_conditional_low = wuhan_conditional_low
    four_project_conditional_high = sum(float(row["high_rmb_100m"]) for row in component_ranges)
    scenario_analysis = {
        "components_rmb_100m": component_ranges,
        "wuhan_complete_build_conditional_rmb_100m": {
            "low": wuhan_conditional_low,
            "high": wuhan_conditional_high,
            "condition": "奕斯伟武汉项目按公开目标建成60万片/月300毫米完整线",
        },
        "current_quantifiable_four_project_scenario_rmb_100m": {
            "low": four_project_conditional_low,
            "high": four_project_conditional_high,
            "included_projects": [row["project_name"] for row in component_ranges],
            "excluded_scope": (
                "未披露设备预算或剩余设备资本开支的中国项目、海外项目、厂房公用工程、已采购未披露部分、"
                "供应商份额、验收和收入确认均未计入。因此146.4亿元只是当前四个可量化项目的条件高情景，"
                "不是中国全部已识别项目的上限。"
            ),
        },
        "method_note": (
            "66.9—81.5亿元只回答‘武汉60万片/月完整线若按目标完整建设，需要多少生产设备投入’。"
            "66.9—146.4亿元是当前四个可量化项目在不同纳入条件下的情景包络：低情景只计武汉低样本，"
            "高情景加入武汉高样本、立昂微两个项目的代理上限和上海超硅规划预算。两者都不是全球TAM、"
            "中国全量市场、设备商订单或年度收入。"
        ),
    }
    outputs["equipment_scenario_calculations"] = {
        "wuhan_equipment_share_of_total": {"low": wuhan_share_low, "high": wuhan_share_high},
        "leon_full_line_remaining_total_budget_rmb_100m": leon_full_remaining,
        "leon_epi_remaining_total_budget_proxy_rmb_100m": leon_epi_remaining_proxy,
        "comparable_epi_equipment_share": epi_equipment_share,
    }
    outputs["equipment_scenario_analysis"] = scenario_analysis
    sam_sensitivity = []
    for row in inputs["china_sam_sensitivity_assumptions"]:
        multiplier = (
            float(row["domestic_process_coverage"])
            * float(row["specification_qualification"])
            * float(row["window_procurement_realization"])
        )
        sam_sensitivity.append(
            {
                **row,
                "combined_multiplier": multiplier,
                "serviceable_amount_rmb_100m": {
                    "low": four_project_conditional_low * multiplier,
                    "high": four_project_conditional_high * multiplier,
                },
                "calculation_base": "当前可量化四项目条件情景",
                "formula": "四项目条件金额×工序覆盖率×规格合格率×窗口采购兑现率",
            }
        )
    company_sensitivity = []
    for sam_row in sam_sensitivity:
        selected_sam = sam_row["serviceable_amount_rmb_100m"]
        for share in inputs["company_combined_share_sensitivity"]:
            company_sensitivity.append(
                {
                    "serviceable_scenario": sam_row["scenario"],
                    "assumed_combined_share": share,
                    "equipment_amount_rmb_100m": {
                        "low": float(selected_sam["low"]) * float(share),
                        "high": float(selected_sam["high"]) * float(share),
                    },
                    "formula": "同一行选定的可服务金额×假设综合份额",
                    "classification": "两层敏感性换算，非公司预测",
                }
            )
    outputs["market_space"] = {
        "global_equipment_demand": {
            "quantified_amount_rmb_100m": None,
            "upper_bound": None,
            "central_estimate": None,
            "status": "目前无法量化",
            "reason": (
                "海外项目缺少2026—2030尚未发生的设备支出、统一设备拆分和采购节奏；"
                "武汉条件情景不能当作全球下限，所以全球TAM不提供金额。"
            ),
        },
        "wuhan_complete_build_conditional_rmb_100m": scenario_analysis["wuhan_complete_build_conditional_rmb_100m"],
        "current_quantifiable_four_project_scenario_rmb_100m": scenario_analysis["current_quantifiable_four_project_scenario_rmb_100m"],
        "china_serviceable_market_sensitivity": sam_sensitivity,
        "company_amount_sensitivity": company_sensitivity,
        "company_som_status": "受限完成；没有工序份额、中标、胜率、合同兑现和收入确认数据。",
    }
    outputs["identified_market"] = {
        "base_project_rmb_100m": {
            "low": round(wuhan["equipment_budget_rmb_100m"]["low"], 4),
            "base": round(wuhan["equipment_budget_rmb_100m"]["base"], 4),
            "high": round(wuhan["equipment_budget_rmb_100m"]["high"], 4),
        },
        "current_quantifiable_four_project_scenario_rmb_100m": {
            "low": round(four_project_conditional_low, 4),
            "high": round(four_project_conditional_high, 4),
        },
        "global_tam_status": "目前无法量化；不以武汉条件情景冒充全球下限",
        "sam_sensitivity": sam_sensitivity,
        "som_sensitivity": company_sensitivity,
        "reason": "可服务金额先从同一四项目条件情景筛选；公司金额再乘选定的可服务金额。两层均是透明敏感性，不是当前份额或收入预测。",
    }
    input_path = output_dir / "model_inputs.json"
    output_path = output_dir / "model_outputs.json"
    write_json(input_path, inputs)
    write_json(output_path, outputs)
    hashes = {
        "model_inputs_sha256": sha256_file(input_path),
        "model_outputs_sha256": sha256_file(output_path),
        "model_code_sha256": sha256_file(Path(__file__)),
    }
    return inputs, outputs, hashes


def _visual(outputs: Mapping[str, Any]) -> dict[str, Any]:
    market = outputs["market_space"]
    wuhan = market["wuhan_complete_build_conditional_rmb_100m"]
    four_projects = market["current_quantifiable_four_project_scenario_rmb_100m"]
    wuhan_citations = _citation_text(["S066", "S011"])
    four_project_citations = _citation_text(["S066", "S068", "S072", "S073", "S011"])
    rows: list[list[Any]] = [
        [
            "武汉60万片/月完整线完整建设",
            f"{float(wuhan['low']):.1f}—{float(wuhan['high']):.1f}亿元",
            "条件情景",
            "两条已投产中国完整线的单位产能生产设备投入区间；项目若缩减、延期或不完整建设，本区间不适用",
            wuhan_citations,
        ],
        [
            "当前可量化的四个中国项目",
            f"{float(four_projects['low']):.1f}—{float(four_projects['high']):.1f}亿元",
            "条件情景包络",
            "低情景只计武汉低样本；高情景加入武汉高样本、立昂微两个代理上限和上海超硅规划预算；不是中国全部项目上限",
            four_project_citations,
        ],
    ]
    for row in market["china_serviceable_market_sensitivity"]:
        amount = row["serviceable_amount_rmb_100m"]
        rows.append(
            [
                f"中国厂商可服务金额：{row['scenario']}",
                f"{float(amount['low']):.1f}—{float(amount['high']):.1f}亿元",
                "研究假设敏感性",
                (
                    f"工序覆盖{float(row['domestic_process_coverage']):.0%}×规格合格"
                    f"{float(row['specification_qualification']):.0%}×窗口采购兑现"
                    f"{float(row['window_procurement_realization']):.0%}；不是公开国产化率"
                ),
                four_project_citations,
            ]
        )
    company_rows = market["company_amount_sensitivity"]
    for sam_row in market["china_serviceable_market_sensitivity"]:
        scoped_rows = [
            row for row in company_rows if row["serviceable_scenario"] == sam_row["scenario"]
        ]
        amount_text = "；".join(
            (
                f"{float(row['assumed_combined_share']):.0%}份额="
                f"{float(row['equipment_amount_rmb_100m']['low']):.2f}—"
                f"{float(row['equipment_amount_rmb_100m']['high']):.2f}亿元"
            )
            for row in scoped_rows
        )
        rows.append(
            [
                f"单家公司金额：{sam_row['scenario']}",
                amount_text,
                "在同一可服务金额上继续做份额敏感性",
                "每个金额=该情景可服务金额×1%/3%/5%/10%综合份额；仍不是订单或收入预测",
                four_project_citations,
            ]
        )
    return _table_visual(
        block_key="equipment_market_space_results",
        title="条件项目金额、可服务金额与公司份额换算",
        subtitle="全球市场目前无法量化；本表只展示武汉完整建设条件、当前可量化四项目情景及沿同一金额链继续计算的敏感性。",
        columns=["要回答的问题", "金额", "数字性质", "如何计算与怎样使用", "逐行证据"],
        rows=rows,
        source_refs=["S066", "S068", "S072", "S073", "S011"],
        sort_order=500,
    )


def _table_visual(
    *,
    block_key: str,
    title: str,
    subtitle: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    source_refs: Sequence[str],
    sort_order: int,
) -> dict[str, Any]:
    table = {"columns": list(columns), "rows": [list(row) for row in rows]}
    return {
        "block_key": block_key,
        "block_type": "table",
        "title": title,
        "subtitle": subtitle,
        "data": {"what": title, "table": table},
        "display_data": table,
        "print_fallback": table,
        "evidence_ref_uri_list": [source_uri(ref) for ref in dict.fromkeys(source_refs)],
        "support_status": "partially_supported",
        "red_flag_level": "none",
        "sort_order": sort_order,
    }


def _format_equipment_investment(values: Any) -> str:
    if not isinstance(values, Mapping) or not values:
        return "公开资料未披露可比较的项目或设备金额"
    labels = {
        "total_project_rmb_100m": ("项目总投资", 1.0, "亿元人民币"),
        "production_equipment_rmb_100m": ("生产设备", 1.0, "亿元人民币"),
        "historical_equipment_rmb_100m": ("历史设备投入", 1.0, "亿元人民币"),
        "machine_original_cost_rmb_100m": ("机器设备原值", 1.0, "亿元人民币"),
        "equipment_and_installation_rmb_100m": ("设备及安装", 1.0, "亿元人民币"),
        "budget_rmb_100m": ("项目预算", 1.0, "亿元人民币"),
        "invested_rmb_100m": ("累计投入", 1.0, "亿元人民币"),
        "remaining_budget_ceiling_rmb_100m": ("剩余预算上限", 1.0, "亿元人民币"),
        "planned_2025_rmb_100m": ("2025年计划投资", 1.0, "亿元人民币"),
        "revised_jpy_100m": ("修订后投资", 1.0, "亿日元"),
        "maximum_subsidy_jpy_100m": ("补贴上限", 1.0, "亿日元"),
        "us_program_usd_bn_about": ("美国项目合计约", 10.0, "亿美元"),
        "invested_to_opening_usd_bn": ("开业前已投入", 10.0, "亿美元"),
        "conditional_additional_usd_bn": ("有条件追加", 10.0, "亿美元"),
        "invested_by_2024_eur_bn_about": ("截至2024年约", 10.0, "亿欧元"),
        "program_krw_tn": ("项目计划", 1.0, "万亿韩元"),
        "project_eur_m": ("项目投资", 0.01, "亿欧元"),
        "production_tools_eur_m_about": ("生产设备约", 0.01, "亿欧元"),
        "jpy_100m": ("项目投资", 1.0, "亿日元"),
        "unused_funds_to_repurpose_rmb_100m": ("拟变更用途的剩余资金", 1.0, "亿元人民币"),
        "equipment_sets": ("设备", 1.0, "台/套"),
        "imported_equipment_sets": ("其中进口设备", 1.0, "台/套"),
    }
    parts: list[str] = []
    for key, value in values.items():
        if key == "historical_design_capacity_wafers_month_10k" or isinstance(value, bool):
            continue
        if key not in labels or value is None:
            continue
        label, multiplier, unit = labels[key]
        number = float(value) * multiplier
        parts.append(f"{label}{number:g}{unit}")
    return "；".join(parts) if parts else "公开资料未披露可比较的项目或设备金额"


PROJECT_SOURCE_REF_OVERRIDES: dict[str, list[str]] = {
    "PRJ001": ["S078", "S066"],
    "PRJ002": ["S012", "S066"],
    "PRJ003": ["S012"],
    "PRJ004": ["S011", "S012", "S066"],
    "PRJ005": ["S067", "S082", "S069", "S070", "S080", "S081", "S071"],
    "PRJ006": ["S068"],
    "PRJ007": ["S072"],
    "PRJ008": ["S073"],
    "PRJ009": ["S074"],
    "PRJ010": ["S074"],
}


def _project_source_refs(project: Mapping[str, Any]) -> list[str]:
    project_id = str(project.get("project_id") or "")
    return list(
        dict.fromkeys(
            PROJECT_SOURCE_REF_OVERRIDES.get(
                project_id,
                [str(ref) for ref in project.get("source_ids") or []],
            )
        )
    )


def _project_database_visual(project_ledger: Mapping[str, Any]) -> dict[str, Any]:
    status_labels = {
        "operating": "已投产",
        "ramping": "正在爬坡",
        "construction": "在建",
        "planning": "规划或募投阶段",
        "rumor": "仅有市场传闻，未纳入测算",
        "excluded": "不属于本轮新增硅片设备需求",
        "historical_status_not_currently_verified": "仅核验到历史状态，当前进展待补充",
        "pending_current_update": "需要补充当前进展",
    }
    stage_summary_overrides = {
        "PRJ001": "已投产，2024年末产能30万片/月",
        "PRJ002": "已投产，2026年4月稳定产能超过65万片/月",
        "PRJ003": "正在爬坡，2026年4月产能超过20万片/月",
        "PRJ004": "在建；2026年5月主体封顶，计划2026年四季度设备搬入、2027年上半年投产、2030年达产",
        "PRJ005": "正在爬坡和客户验证；2025年300毫米平均瓶颈能力30.58万片/月、利用率75.18%",
        "PRJ006": "募投规划阶段，计划建设期24个月，仍待资金与采购落地",
        "PRJ007": "在建，2025年末工程进度48.97%",
        "PRJ008": "在建；2025年末工程进度20.60%，因行业开工率放缓而延期至2027年12月",
        "PRJ009": "在建；年报称有序推进，但未披露可复核工程进度和明确达产日",
        "PRJ010": "在建，与重掺外延项目配套，未披露更具体进度",
        "PRJ011": "规划或升级阶段；宜兴70万片/月与既有厂房升级后35万片/月的关系未说明，徐州60万片/月属于另一基地",
        "PRJ012": "仅核验到2023年设备采购规模，公开资料不足以判断2026年当前建设或爬坡状态",
        "PRJ013": "按日本经产省2026年修订计划在建；首段晶体能力2028年启动，第二段晶体能力2030年末启动，主要加工能力在2031年",
        "PRJ014": "正在客户验证和产能爬坡；2025年开幕后，最新披露仍处验证与爬坡阶段",
        "PRJ015": "2025年三季度仍在试产送样，并以2026年量产为目标；公开资料不足以确认目标是否兑现",
        "PRJ016": "仍属三、四期及追加40亿美元投资意向，未有确定开工或投产日",
        "PRJ017": "已投产，2023年产出首批晶圆，主要折旧自2025年起",
        "PRJ018": "正在爬坡；2026年公司材料称新厂爬坡将支持当年经营",
        "PRJ019": "2024年厂房完工后分期装机；当前已装能力低于满配，后续随客户需求爬坡",
        "PRJ020": "已排除；本轮未找到2026—2030年新增半导体硅片制造项目，伊势崎项目属于光刻材料",
        "PRJ022": "规划阶段；2025年半年度报告披露郑州拟新增6万片/月，未披露可复核投产日期",
        "PRJ023": "拟终止原扩产募投项目；产品为刻蚀设备用硅材料，不属于半导体硅片",
    }
    rows: list[list[Any]] = []
    refs: list[str] = []
    for project in project_ledger["projects"]:
        row_refs = _project_source_refs(project)
        if not row_refs:
            # 无来源的匿名传闻保留在内部 project_ledger，公开表格不为其伪造证据。
            continue
        capacity = (
            f"{float(project['capacity']):g}{project['capacity_unit']}"
            if project.get("capacity") is not None
            else "公开资料未披露可比较产能"
        )
        stage = status_labels.get(str(project.get("status")), str(project.get("status") or "公开资料不足以判断"))
        evidence = str(project.get("status_evidence") or "公开资料不足以进一步判断建设进度")
        schedule = str(project.get("schedule") or "未披露明确时间")
        stage_summary = stage_summary_overrides.get(
            str(project.get("project_id") or ""),
            f"{stage}；{schedule}；{evidence}",
        )
        treatment = str(project.get("equipment_demand_treatment") or "只保留项目事实，不进入设备需求测算")
        if str(project.get("company")) == "Shin-Etsu Chemical":
            treatment = "本轮未找到2026—2030新增硅片项目；伊势崎项目是光刻材料，排除设备测算"
        rows.append(
            [
                str(project["company"]),
                f"{project['location']}｜{project['product']}",
                capacity,
                stage_summary,
                _format_equipment_investment(project.get("investment")),
                treatment,
                _citation_text(row_refs),
            ]
        )
        refs.extend(row_refs)
    return _table_visual(
        block_key="wafer_maker_equipment_project_database",
        title="硅片厂扩产与设备需求项目库（22项有可核验来源）",
        subtitle="内部台账共筛查23项；公开表只展示22项有可核验来源的项目。另1项匿名传闻只留内部台账且不入模型，不为缺失来源补造证据。历史设备投入只校准投资强度，不冒充2026—2030年新增订单。",
        columns=["公司或项目", "地区与产品", "公开产能", "阶段与时间", "公开投资或设备额", "如何计入设备需求", "逐行证据"],
        rows=rows,
        source_refs=refs,
        sort_order=520,
    )


def _equipment_chain_visual(equipment_landscape: Mapping[str, Any]) -> dict[str, Any]:
    rows = [
        [
            f"{row['step']}. {row['segment']}",
            "、".join(str(value) for value in row["equipment"]),
            "、".join(str(value) for value in row["key_outputs"]),
            "、".join(str(value) for value in row["representative_suppliers"]),
            _citation_text([str(ref) for ref in row.get("evidence_source_ids") or []]),
        ]
        for row in equipment_landscape["equipment_map"]
    ]
    refs = [
        str(ref)
        for row in equipment_landscape["equipment_map"]
        for ref in row.get("evidence_source_ids") or []
    ]
    refs.extend(
        str(ref)
        for row in equipment_landscape.get("size_and_product_differences") or []
        for ref in row.get("evidence_source_ids") or []
    )
    return _table_visual(
        block_key="silicon_wafer_equipment_chain_map",
        title="硅片制造设备链图谱",
        subtitle="从晶体生长到包装自动化列出九道工序。厂商列只表示存在公开产品或历史参与记录，不代表已取得本轮扩产订单；200毫米、300毫米、外延与SOI产线不能机械共用同一价值量。",
        columns=["制造环节", "核心设备", "设备控制的结果", "公开产品或历史参与厂商", "逐行证据"],
        rows=rows,
        source_refs=refs,
        sort_order=530,
    )


def _specific_supplier_relation_refs(row: Mapping[str, Any]) -> list[str]:
    row_refs = [str(ref) for ref in row.get("source_ids") or []]
    supplier_name = str(row.get("supplier") or "")
    if "S004" in row_refs:
        if "Applied Materials" in supplier_name:
            fact_ref = "S069"
        elif "KLA" in supplier_name:
            fact_ref = "S070"
        elif "供应商B1" in supplier_name or "匿名研磨设备供应商" in supplier_name:
            fact_ref = "S080"
        elif "Okamoto" in supplier_name:
            fact_ref = "S081"
        else:
            fact_ref = "S071"
        row_refs = [fact_ref if ref == "S004" else ref for ref in row_refs]
    if "S003" in row_refs:
        segment = str(row.get("equipment_segment") or "")
        if "单晶" in segment:
            fact_refs = ["S077"]
        elif "研磨减薄" in segment:
            fact_refs = ["S076"]
        elif "CMP" in segment and "研磨" in segment:
            fact_refs = ["S075", "S076"]
        else:
            fact_refs = ["S075"]
        row_refs = [ref for ref in row_refs if ref != "S003"]
        row_refs = [*fact_refs, *row_refs]
    if "S030" in row_refs and (
        "晶升股份" in supplier_name or "晶盛机电" in supplier_name
    ):
        row_refs = ["S079" if ref == "S030" else ref for ref in row_refs]
    if supplier_name == "晶盛机电" and "TCL中环" in str(
        row.get("wafer_company_or_project") or ""
    ):
        row_refs = [ref for ref in row_refs if ref != "S006"]
    if "S005" in row_refs:
        row_refs = [ref for ref in row_refs if ref != "S005"]
        row_refs = ["S073", "S074", *row_refs]
    return list(dict.fromkeys(row_refs))


def _supplier_relationship_visual(equipment_landscape: Mapping[str, Any]) -> dict[str, Any]:
    grade_labels = {
        "公开确认": "已有公开合同、采购、验收或监管披露确认",
        "公开确认-历史少量交付": "仅确认历史少量交付，不能据此推断本轮份额",
        "公开确认-历史": "仅确认历史供应关系，当前项目订单尚未披露",
        "公开确认-合作关系": "合作或采购渠道已确认，新项目合同尚未披露",
        "公开确认但客户未具名": "产品销售或验证已确认，但不能映射到具体硅片厂",
        "公开确认但尚未完成验收": "采购或交付已确认，最终验收和收入仍有条件",
        "公开确认但匿名": "合同已披露但供应商匿名，不能自行补全名称",
        "较高概率候选": "历史关系支持候选判断，但当前项目没有具名合同",
        "产业链可能": "产品能力匹配，但当前项目没有订单或验收证据",
        "目前没有直接证据": "目前没有直接供应商证据",
    }
    rows: list[list[Any]] = []
    refs: list[str] = []
    for row in equipment_landscape["supplier_relations"]:
        assessment = grade_labels.get(str(row["grade"]), str(row["grade"]))
        row_refs = _specific_supplier_relation_refs(row)
        supplier_name = str(row["supplier"])
        rows.append(
            [
                str(row["wafer_company_or_project"]),
                str(row["equipment_segment"]),
                supplier_name,
                f"{assessment}；{row['status_detail']}",
                _citation_text(row_refs),
            ]
        )
        refs.extend(row_refs)
    return _table_visual(
        block_key="wafer_maker_equipment_supplier_relationships",
        title="硅片厂与设备供应商关系矩阵",
        subtitle="只把具名合同、采购、交付或验收写成已确认关系；产品匹配和历史合作单独标示，不能据此推断新项目订单或市场份额。",
        columns=["硅片厂或项目", "设备环节", "设备供应商", "公开证据和当前判断", "逐行证据"],
        rows=rows,
        source_refs=refs,
        sort_order=540,
    )


def _demand_to_equipment_visual() -> dict[str, Any]:
    refs = [str(ref) for row in DEMAND_TO_EQUIPMENT_ROWS for ref in row["refs"]]
    rows = [
        [
            row["driver"],
            row["wafer"],
            row["process"],
            row["suppliers"],
            row["boundary"],
            _citation_text(row["refs"]),
        ]
        for row in DEMAND_TO_EQUIPMENT_ROWS
    ]
    return _table_visual(
        block_key="demand_wafer_process_supplier_chain",
        title="下游需求怎样改变硅片产品、工序与供应商机会",
        subtitle="先把晶圆厂扩产映射到硅片品类，再映射到制造工序；应用需求不能越过硅片采购和有效产能直接变成设备订单。",
        columns=["需求来源", "主要硅片品类", "新增或强化的设备工序", "供应商观察范围", "不能怎样外推", "逐行证据"],
        rows=rows,
        source_refs=refs,
        sort_order=505,
    )


def _soi_process_visual() -> dict[str, Any]:
    refs = [str(ref) for row in SOI_PROCESS_ROWS for ref in row["refs"]]
    rows = [
        [
            row["step"],
            row["equipment"],
            row["difference"],
            row["supplier"],
            _citation_text(row["refs"]),
        ]
        for row in SOI_PROCESS_ROWS
    ]
    return _table_visual(
        block_key="soi_proprietary_process_chain",
        title="SOI专有九步工序与设备链",
        subtitle="氢离子注入剥离/键合型SOI在普通抛光片之后增加专用工序；产品能力或研发状态不等于已经取得Soitec或其他项目订单。",
        columns=["工序", "核心设备", "相对普通硅片的新增控制点", "现有供应商证据", "逐行证据"],
        rows=rows,
        source_refs=refs,
        sort_order=535,
    )


def _supplier_disposition_visual() -> dict[str, Any]:
    refs = [ref for _company, _status, _reason, row_refs in SUPPLIER_DISPOSITION_ROWS for ref in row_refs]
    rows = [
        [company, status, reason, _citation_text(row_refs)]
        for company, status, reason, row_refs in SUPPLIER_DISPOSITION_ROWS
        if row_refs
    ]
    return _table_visual(
        block_key="named_supplier_inclusion_observation_exclusion",
        title="22家有可核验来源的设备候选筛选结果",
        subtitle="本轮共筛查27家；浙江芯晖装备与西安芯晖设备按独立法人分列。公开表展示22家至少有一条可点击产品、客户或边界材料的候选；其余5家以带日期的检索日志保留在审计层。排除只针对本轮核心排序，不代表永久没有相关能力。",
        columns=["设备厂商", "本轮处理", "为什么", "逐行证据"],
        rows=rows,
        source_refs=refs,
        sort_order=545,
    )


def _listed_company_ranking_visual() -> dict[str, Any]:
    refs = [str(ref) for row in LISTED_COMPANY_RANKING_ROWS for ref in row["refs"]]
    rows = [
        [
            f"{row['rank']}. {row['company']}",
            row["process"],
            row["customer"],
            row["order"],
            row["financial"],
            row["judgment"],
            _citation_text(row["refs"]),
        ]
        for row in LISTED_COMPANY_RANKING_ROWS
    ]
    return _table_visual(
        block_key="listed_equipment_company_evidence_ranking",
        title="10家上市设备公司的证据验证优先级",
        subtitle="排序综合产品直接性、客户与验证、当期订单、专题收入可穿透度及技术壁垒；它表示先研究谁，不是收益率预测。集团毛利率只作经营背景。",
        columns=["优先级与公司", "明确工序与壁垒", "客户或验证", "2026—2030订单可见度", "业务暴露与财务口径", "当前判断", "逐行证据"],
        rows=rows,
        source_refs=refs,
        sort_order=550,
    )


def _listed_financial_snapshot_visual() -> dict[str, Any]:
    refs = [
        str(ref)
        for row in LISTED_FINANCIAL_SNAPSHOT_ROWS
        for ref in row["refs"]
    ]
    rows = [
        [
            row["company"],
            row["market_cap"],
            row["valuation"],
            row["profitability"],
            row["per_share"],
            f"{row['boundary']} {_citation_text(row['refs'])}",
        ]
        for row in LISTED_FINANCIAL_SNAPSHOT_ROWS
    ]
    return _table_visual(
        block_key="listed_equipment_company_financial_snapshot",
        title="7家设备侧上市标的最新估值与盈利快照",
        subtitle=(
            "估值按各自行情日，ROE、ROA、EPS和BPS按表内注明的最近报告期；每股指标保留证券原币。"
            "不同财年、币种和业务组合不能直接排名，表中数值只用于判断集团承载力与估值位置。"
        ),
        columns=["公司、来源与市场日", "市值", "PE / PB / PS", "ROE / ROA", "EPS / BPS（原币）", "使用边界与证据"],
        rows=rows,
        source_refs=refs,
        sort_order=555,
    )


def build_pack(*, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    research_question = extract_primary_research_question(INTAKE_PATH)
    financial_audit = _load_json(FINANCIAL_AUDIT_PATH)
    audited_financial_targets, audited_financial_sources, financial_audit_summary = (
        apply_financial_evidence_audit(
            _load_json(FINANCIAL_TARGETS_PATH),
            _load_json(FINANCIAL_SOURCES_PATH),
            financial_audit,
        )
    )
    # The frozen financial inputs retain provider field names; the equipment
    # pack publishes their natural Chinese labels without mutating those files.
    audited_financial_targets = _humanize_public_aliases(audited_financial_targets)
    audited_financial_sources = _humanize_public_aliases(audited_financial_sources)
    evidence_audit = _load_json(EQUIPMENT_AUDIT_PATH)
    audited_source_rows, source_audit_summary = apply_source_catalog_corrections(
        _load_json(EQUIPMENT_DIR / "sources.json"),
        evidence_audit,
    )
    sources = _source_catalog(
        audited_source_rows,
        financial_targets_payload=audited_financial_targets,
        financial_sources_payload=audited_financial_sources,
    )
    sources_by_ref = {source["ref"]: source for source in sources}
    raw_data_points = _load_json(EQUIPMENT_DIR / "data_points.json")
    audited_data_points, data_point_audit_summary = apply_data_point_evidence_audit(
        raw_data_points,
        evidence_audit,
        minimum_retained=100,
    )
    precise_data_point_sources = {
        "DP054": "S082",
        "DP055": "S069",
        "DP056": "S069",
        "DP057": "S080",
        "DP058": "S070",
        "DP059": "S070",
        "DP060": "S070",
        "DP061": "S071",
        "DP062": "S071",
        "DP063": "S068",
        "DP064": "S068",
        "DP065": "S068",
        "DP066": "S068",
        "DP067": "S068",
        "DP068": "S068",
    }
    for point in audited_data_points:
        precise_ref = precise_data_point_sources.get(str(point.get("id") or ""))
        if precise_ref:
            point["source_ids"] = [precise_ref]
    audited_data_points = [*audited_data_points, *SUPPLEMENTAL_DATA_POINTS]
    data_points = normalize_agent_data_points(audited_data_points, sources_by_ref=sources_by_ref)
    anonymized_label_audit_records: list[dict[str, str]] = []
    for point in data_points:
        for field in (
            "data_point_title",
            "metric",
            "scope_key",
            "interpretation",
            "research_use",
            "note",
            "value_text",
        ):
            if point.get(field) is not None:
                point[field] = _humanize_public_aliases(point[field])
        for excerpt_field in ("source_excerpt", "source_excerpt_zh"):
            excerpt = str(point.get(excerpt_field) or "")
            if "供应商B1" in excerpt or "匿名供应商B1" in excerpt:
                anonymized_label_audit_records.append(
                    {
                        "source_ref": str(point.get("source_ref") or ""),
                        "data_point_key": str(point.get("data_point_key") or ""),
                        "field": excerpt_field,
                        "original_excerpt_sha256": _sha256_json(excerpt),
                        "public_alias": "招股书匿名研磨设备供应商",
                    }
                )
                point[excerpt_field] = _humanize_public_aliases(excerpt)
    data_points_by_source: dict[str, list[dict[str, Any]]] = {}
    for index, point in enumerate(data_points, start=1):
        point["data_point_key"] = f"equipment_dp_{index:03d}"
        data_points_by_source.setdefault(str(point.get("source_ref") or ""), []).append(point)
    source_direct_excerpt_audit = _apply_direct_source_excerpts(sources, data_points)
    for source in sources:
        for field in ("title", "title_zh"):
            if source.get(field) is not None:
                source[field] = _humanize_public_aliases(source[field])
    sources_by_ref = {source["ref"]: source for source in sources}
    final_data_point_audit, final_data_point_audit_sha256 = _write_final_data_point_audit(
        data_points,
        sources_by_ref=sources_by_ref,
        output_dir=output_dir,
    )
    data_point_audit_summary = {
        **data_point_audit_summary,
        "supplemental_research_point_count": len(SUPPLEMENTAL_DATA_POINTS),
        "final_retained_count": len(data_points),
        "final_itemized_audit_count": final_data_point_audit["itemized_result_count"],
        "final_itemized_audit_failure_count": final_data_point_audit["failure_count"],
        "final_data_point_set_sha256": final_data_point_audit["data_point_set_sha256"],
    }
    inputs, outputs, model_hashes = _model_bundle(output_dir)
    project_ledger = _humanize_public_aliases(
        _load_json(EQUIPMENT_DIR / "equipment_project_ledger.json")
    )
    for project in project_ledger["projects"]:
        project_id = str(project.get("project_id") or "")
        project["source_ids"] = _project_source_refs(project)
        if project_id == "PRJ008":
            project["equipment_demand_treatment"] = (
                "只在四项目条件高情景中按剩余预算代理纳入；延期意味着采购、验收和收入确认可能继续后移。"
            )
        elif project_id == "PRJ012":
            project["status"] = "historical_status_not_currently_verified"
            project["status_evidence"] = (
                "本轮仅核验到2023年设备采购规模；公开资料不足以判断2026年当前建设或爬坡状态。"
            )
            project["schedule"] = "2023年历史披露；当前状态待补充"
            project["equipment_demand_treatment"] = (
                "仅用于观察历史进口依赖和整线设备数量级，不将562台套再次当作2026—2030新订单。"
            )
        elif project_id == "PRJ015":
            project["status"] = "pending_current_update"
            project["status_evidence"] = (
                "可核验信息止于2025年三季度试产送样和2026年量产目标；本轮没有找到目标是否兑现的当前一手更新。"
            )
            project["equipment_demand_treatment"] = (
                "量产状态待更新；在取得2026投产或客户认证材料前，不把后续瓶颈设备写成已发生需求。"
            )
        if str(project.get("company")) == "Shin-Etsu Chemical":
            project["status_evidence"] = (
                "本轮负面检索未找到2026—2030新增半导体硅片制造项目；"
                "伊势崎项目明确属于光刻材料"
            )
            project["equipment_demand_treatment"] = (
                "光刻材料项目排除；保留信越化学未找到新增硅片项目的一手证据这一结论"
            )
    equipment_landscape = _humanize_public_aliases(
        _load_json(EQUIPMENT_DIR / "equipment_map_and_supplier_relations.json")
    )
    precise_relations: list[dict[str, Any]] = []
    for relation in equipment_landscape.get("supplier_relations") or []:
        supplier_name = str(relation.get("supplier") or "")
        wafer_name = str(relation.get("wafer_company_or_project") or "")
        if supplier_name == "晶盛机电" and (
            "上海新昇" in wafer_name or "立昂微" in wafer_name or "金瑞泓" in wafer_name
        ):
            # 原台账把晶升股份历史交付误归给晶盛机电；监管原文只支持晶盛主要供应TCL中环。
            continue
        if supplier_name == "晶盛机电" and "TCL中环" in wafer_name:
            relation["status_detail"] = (
                "监管披露其为TCL中环半导体级单晶硅炉主要国内供应商；"
                "当前宜兴项目份额未公开"
            )
        if "Okamoto" in supplier_name:
            relation["status_detail"] = (
                "招股书确认与Okamoto等终端设备生产商直接合作；"
                "具体机型和本轮项目合同未披露"
            )
        relation["source_ids"] = _specific_supplier_relation_refs(relation)
        if str(relation.get("supplier") or "") in {
            "浙江芯晖装备",
            "西安芯晖设备（原西安奕斯伟设备）",
        }:
            relation["source_ids"] = list(
                dict.fromkeys([*(relation.get("source_ids") or []), "S064"])
            )
        precise_relations.append(relation)
    equipment_landscape["supplier_relations"] = precise_relations
    for step in equipment_landscape.get("equipment_map") or []:
        suppliers = "、".join(str(value) for value in step.get("representative_suppliers") or [])
        if "芯晖" in suppliers:
            step["evidence_source_ids"] = list(
                dict.fromkeys([*(step.get("evidence_source_ids") or []), "S064"])
            )
        if "SpeedFam" in suppliers or "Lapmaster" in suppliers or "Okamoto" in suppliers:
            step["evidence_source_ids"] = list(
                dict.fromkeys(
                    [*(step.get("evidence_source_ids") or []), "S071", "S080", "S081"]
                )
            )

    entity_specs_by_key = {spec["key"]: spec for spec in ENTITY_SPECS}
    entities = []
    entity_sections = []
    for spec in ENTITY_SPECS:
        refs = _unique_refs(list(spec["refs"]), sources_by_ref)
        entity = build_segment_entity(
            {
                "key": spec["key"],
                "canonical_name": spec["name"],
                "display_name": spec["name"],
                "description": spec["description"],
                "factor_inputs": _factor_inputs(spec, sources_by_ref, data_points_by_source),
                "band_reason": "当前只比较研究优先级；项目订单、工序份额和收入确认仍需补充直接证据。",
            },
            sources_by_ref=sources_by_ref,
            as_of_date=AS_OF_DATE,
        )
        _apply_factor_specific_information_excerpts(
            entity,
            data_points_by_source=data_points_by_source,
            sources_by_ref=sources_by_ref,
        )
        _rewrite_factor_score_rationales(entity)
        entities.append(entity)
        entity_sections.append(_entity_section(spec, refs))

    financial_targets = _financial_target_map(audited_financial_targets)
    targets: list[dict[str, Any]] = []
    target_index = 1
    audited_target_assignments = (
        ("pva_tepla", "semiconductor_crystal_growth_tools"),
        ("accretech", "wafer_grinding_polishing_tools"),
        ("jingsheng", "semiconductor_crystal_growth_tools"),
        ("kla", "bare_wafer_metrology_tools"),
    )
    for target_id, entity_key in audited_target_assignments:
        targets.append(
            _build_target(
                target_id=target_id,
                entity_spec=entity_specs_by_key[entity_key],
                financial_targets=financial_targets,
                sources_by_ref=sources_by_ref,
                index=target_index,
            )
        )
        target_index += 1
    targets.append(
        _build_supplemental_financial_target(
            target_id="crystal_rise",
            entity_key="semiconductor_crystal_growth_tools",
            product_source_ref="S079",
            sources_by_ref=sources_by_ref,
            process="12英寸半导体单晶生长设备",
            evidence="监管文件确认向上海新昇、立昂微交付12英寸半导体单晶炉",
            current_project_gap="2026—2030新增项目合同、验收和单晶炉专题财务",
            priority="P1",
            index=target_index,
        )
    )
    target_index += 1
    targets.append(
        _build_supplemental_financial_target(
            target_id="applied_materials",
            entity_key="silicon_epitaxy_tools",
            product_source_ref="S069",
            sources_by_ref=sources_by_ref,
            process="硅外延设备",
            evidence="上海超硅招股书披露应用材料常压外延系统合同；产品能力另由公司硅外延平台资料交叉验证",
            current_project_gap="上海超硅新外延项目和立昂微项目的具名合同、腔体数量与专题收入",
            priority="P1",
            index=target_index,
        )
    )
    target_index += 1
    targets.append(
        _build_supplemental_financial_target(
            target_id="huahai_qingke",
            entity_key="wafer_final_clean_automation",
            product_source_ref="S033",
            sources_by_ref=sources_by_ref,
            process="大硅片终洗以及相关研磨/CMP设备",
            evidence="公司披露大硅片终洗设备完成验证并实现销售，但没有公开客户名称",
            current_project_gap="目标硅片厂具名订单、复购、终验与硅片专用收入",
            priority="P2",
            index=target_index,
        )
    )

    builder = RunPackBuilder(
        slug=SLUG,
        research_question=research_question,
        display_title=DISPLAY_TITLE,
        requested_by="codex_opportunity_lens_research_workflow_v2",
        run_mode="c_hybrid",
        quality_profile="deep_research",
        problem_statement="核验2026—2030年硅片厂扩产如何转化为制造设备订单，并识别具有直接客户或产品证据的供应商与上市标的。",
        intake={
            "research_question": research_question,
            "available_materials_choice": "B",
            "intake_material_type": "papers_folder",
            "materials_delivery_note": "本地硅片资料只作为背景和检索种子；设备供应关系、扩产状态和财务均重新用公开一手资料核验。",
            "evidence_policy": "balanced",
            "time_window": {"core": "2026—2030", "history": "2020年以来扩产、周期与国产化"},
            "research_scope": {"geography": "全球", "industry": "半导体硅片制造设备", "exclusion": "芯片晶圆厂通用前道设备与光伏硅片"},
            "special_constraints": {"supplier_relation": "无具名证据不写成供应关系", "market_model": "项目金额、订单和收入确认分开"},
            "field_origin": {"research_question": "user_provided", "scope": "user_provided", "model": "user_required_and_researcher_refined"},
            "default_accepted": {},
        },
    )
    builder.sources = sources
    builder.evidence_groups = {source["ref"]: source["independence_key"] for source in sources}
    builder.data_points = data_points
    builder.claims = [
        {
            "source_ref": ref,
            "claim_text": _humanize_public_aliases(sources_by_ref[ref]["excerpt_zh"]),
            "source_excerpt": sources_by_ref[ref]["excerpt"],
            **({"source_excerpt_zh": sources_by_ref[ref]["excerpt_zh"]} if sources_by_ref[ref]["language"] != "zh-CN" else {}),
            "claim_type": "observed_fact",
            "note": "只在原始来源覆盖范围内使用，不外推未披露客户或订单。",
        }
        for ref in (
            "S001", "S003", "S004", "S005", "S011", "S014", "S018", "S027",
            "S028", "S030", "S031", "S034", "S036", "S038", "S045", "S055",
            "S056", "S057", "S058", "S059", "S060", "S061", "S062", "S063",
            "S064", "S065", "S066", "S067", "S068", "S069", "S070", "S071",
            "S072", "S073", "S074", "S075", "S076", "S077", "S078",
            "S079", "S080", "S081", "S082", "FIN-PVA-06",
        )
    ]
    builder.entities = entities
    builder.entity_sections = entity_sections
    builder.entity_investment_targets = targets
    builder.sections = _main_sections()
    builder.visuals = [
        _visual(outputs),
        _demand_to_equipment_visual(),
        _project_database_visual(project_ledger),
        _equipment_chain_visual(equipment_landscape),
        _soi_process_visual(),
        _supplier_relationship_visual(equipment_landscape),
        _supplier_disposition_visual(),
        _listed_company_ranking_visual(),
        _listed_financial_snapshot_visual(),
    ]
    builder.search_plan = [
        {"axis_key": "downstream_demand_transmission", "query_text": "先进逻辑、DRAM/HBM、NAND、功率与SOI项目怎样改变硅片品类和设备工序", "languages": ["zh", "en", "ko"], "status": "completed"},
        {"axis_key": "wafer_maker_projects", "query_text": "全球硅片厂扩产、项目进度、设备搬入与客户认证", "languages": ["zh", "en", "ja", "ko"], "status": "completed"},
        {"axis_key": "equipment_contracts", "query_text": "硅片厂招股书、问询回复和设备商订单中的具名供应关系", "languages": ["zh", "en", "ja"], "status": "completed"},
        {"axis_key": "process_boundary", "query_text": "长晶、切磨抛、外延、终洗和裸片检测的直接产品范围", "languages": ["zh", "en", "ja"], "status": "completed"},
        {"axis_key": "counterevidence", "query_text": "项目延期、利用率、售价、验收失败和资本开支后移", "languages": ["zh", "en", "ja", "ko"], "status": "completed"},
    ]
    builder.supplement_requests = [
        {
            "entity_key": "semiconductor_crystal_growth_tools",
            "request_title": "补充武汉项目设备采购与搬入清单",
            "request_detail": "优先取得采购公告、品牌、金额、设备数量、进口备案和首批搬入时间，用真实订单替换项目级估算。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("S011"),
        },
        {
            "entity_key": "wafer_grinding_polishing_tools",
            "request_title": "补充国产设备最终验收与量产指标",
            "request_detail": "补充平整度、缺陷、颗粒、稼动率、最终验收和复购，区分已交付与已形成收入。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("S076"),
        },
        {
            "entity_key": "silicon_epitaxy_tools",
            "request_title": "补充外延项目开工与供应商合同",
            "request_detail": "跟踪上海超硅募资、立昂微延期项目和武汉外延配置，核对反应腔数量、品牌和验收。",
            "priority": "p2",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("S004"),
        },
        {
            "entity_key": "semiconductor_crystal_growth_tools",
            "request_title": "补充海外项目尚未发生的设备资本开支",
            "request_detail": "需要SUMCO、Soitec、GlobalWafers、Siltronic和SK Siltron按阶段披露剩余设备支出、设备拆分与2026—2030采购节奏，才能解除全球市场上限限制。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("S014"),
        },
        {
            "entity_key": "bare_wafer_metrology_tools",
            "request_title": "补充公司份额与收入确认所需合同证据",
            "request_detail": "需要逐工序中标、合同金额、竞争供应商、交付验收、收入确认和回款，才能把项目池敏感性推进为单家公司可得金额。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("S034"),
        },
    ]
    builder.audit_issues = []
    builder.review_records = []
    pack = builder.build(publication_mode="stage")
    pack["as_of_date"] = AS_OF_DATE
    pack["model_artifacts"] = {
        **model_hashes,
        "evidence_audit_sha256": sha256_file(EQUIPMENT_AUDIT_PATH),
        "final_data_point_evidence_audit_sha256": final_data_point_audit_sha256,
        "financial_evidence_audit_sha256": sha256_file(FINANCIAL_AUDIT_PATH),
        "financial_targets_input_sha256": sha256_file(FINANCIAL_TARGETS_PATH),
        "financial_sources_input_sha256": sha256_file(FINANCIAL_SOURCES_PATH),
        "method": (
            "武汉完整线按两个已投产项目的生产设备投入强度实时复算；立昂微只用剩余项目预算与可比设备占比形成受限上限；"
            "上海超硅规划预算只进入四项目条件高情景。全球市场不提供金额；中国可服务金额从同一四项目条件情景筛选，"
            "公司金额再乘选定的可服务金额。两层仅作显式研究假设敏感性，不输出没有证据支持的年度订单、收入或利润。"
        ),
    }
    pack["evidence_audit"] = {
        "data_points": data_point_audit_summary,
        "sources": source_audit_summary,
        "audit_sha256": sha256_file(EQUIPMENT_AUDIT_PATH),
        "final_itemized_audit_sha256": final_data_point_audit_sha256,
    }
    equipment_financial_refs = sorted(
        {
            str(point.get("evidence_ref_uri") or "").replace("source_ref:", "")
            for target in targets
            for point in target.get("target_data_points") or []
            if point.get("evidence_ref_uri")
        }
    )
    equipment_financial_points = [
        point
        for target in targets
        for point in target.get("target_data_points") or []
    ]
    pack["financial_evidence_audit"] = {
        "schema_version": "silicon_wafer_equipment_financial_scope.v1",
        "scope": "仅审计本设备研究实际展示的7家上市标的；不携带需求侧标的或未引用来源。",
        "audited_target_names": [str(target["target_name"]) for target in targets],
        "audited_target_count": len(targets),
        "source_refs": equipment_financial_refs,
        "source_ref_count": len(equipment_financial_refs),
        "target_data_point_count": len(equipment_financial_points),
        "financial_history_point_count": sum(
            1
            for point in equipment_financial_points
            if point.get("metric_category") == "financial_history"
        ),
        "current_valuation_point_count": sum(
            1
            for point in equipment_financial_points
            if point.get("metric_category") == "current_valuation_and_profitability"
        ),
        "full_audit_sha256": sha256_file(FINANCIAL_AUDIT_PATH),
        "supplement_code_sha256": sha256_file(FINANCIAL_SUPPLEMENT_MODULE_PATH),
    }
    pack["project_ledger"] = project_ledger
    pack["equipment_landscape"] = equipment_landscape
    pack["negative_supplier_search_logs"] = [dict(row) for row in NEGATIVE_SUPPLIER_SEARCH_LOGS]
    pack["tracking_framework"] = {
        "update_frequency": "季度；设备搬入和采购公告出现时事件驱动更新",
        "fields": ["项目产能和产品", "正式合同", "交付安装", "转固或最终验收", "收入确认和回款", "国产设备量产指标"],
    }
    anonymized_label_audit = {
        "audit_version": "equipment.public_anonymous_supplier_alias.v1",
        "as_of_date": AS_OF_DATE,
        "record_count": len(anonymized_label_audit_records),
        "records": anonymized_label_audit_records,
        "public_alias": "招股书匿名研磨设备供应商",
        "status": "pass",
    }
    anonymized_label_audit_path = output_dir / "anonymized_label_audit.json"
    write_json(anonymized_label_audit_path, anonymized_label_audit)
    pack["model_artifacts"]["anonymized_label_audit_sha256"] = sha256_file(
        anonymized_label_audit_path
    )
    target_public_content_audit = _build_target_public_content_audit(pack)
    target_public_content_path = output_dir / "target_public_content_audit.json"
    write_json(target_public_content_path, target_public_content_audit)
    pack["target_public_content_audit"] = target_public_content_audit
    pack["model_artifacts"]["target_public_content_audit_sha256"] = sha256_file(
        target_public_content_path
    )
    factor_public_content_audit = _build_factor_public_content_audit(
        pack=pack,
        data_points_by_source=data_points_by_source,
    )
    factor_public_content_path = output_dir / "factor_public_content_audit.json"
    write_json(factor_public_content_path, factor_public_content_audit)
    pack["factor_public_content_audit"] = factor_public_content_audit
    pack["model_artifacts"]["factor_public_content_audit_sha256"] = sha256_file(
        factor_public_content_path
    )
    critical_public_fact_citation_audit = _build_critical_public_fact_citation_audit(
        pack
    )
    critical_public_fact_citation_path = (
        output_dir / "critical_public_fact_citation_audit.json"
    )
    write_json(
        critical_public_fact_citation_path,
        critical_public_fact_citation_audit,
    )
    pack["critical_public_fact_citation_audit"] = critical_public_fact_citation_audit
    pack["model_artifacts"]["critical_public_fact_citation_audit_sha256"] = (
        sha256_file(critical_public_fact_citation_path)
    )
    source_direct_excerpt_path = output_dir / "source_direct_excerpt_audit.json"
    write_json(source_direct_excerpt_path, source_direct_excerpt_audit)
    pack["source_direct_excerpt_audit"] = source_direct_excerpt_audit
    pack["model_artifacts"]["source_direct_excerpt_audit_sha256"] = sha256_file(
        source_direct_excerpt_path
    )
    source_traceability_audit = _build_source_traceability_audit(
        pack=pack,
        model_inputs=inputs,
        direct_excerpt_audit=source_direct_excerpt_audit,
    )
    source_traceability_path = output_dir / "source_traceability_audit.json"
    write_json(source_traceability_path, source_traceability_audit)
    pack["source_traceability_audit"] = source_traceability_audit
    pack["model_artifacts"]["source_traceability_audit_sha256"] = sha256_file(
        source_traceability_path
    )
    return pack


def write_bundle(*, output_dir: Path) -> Path:
    pack = build_pack(output_dir=output_dir)
    path = write_pack_bundle(pack, output_dir=output_dir, audit_profile="generic")
    write_json(output_dir / "source_catalog.json", pack["sources"])
    write_json(output_dir / "project_ledger.json", pack["project_ledger"])
    write_json(output_dir / "equipment_landscape.json", pack["equipment_landscape"])
    write_json(
        output_dir / "artifact_hashes.json",
        {
            "run_pack_sha256": sha256_file(path),
            "model_inputs_sha256": sha256_file(output_dir / "model_inputs.json"),
            "model_outputs_sha256": sha256_file(output_dir / "model_outputs.json"),
            "model_code_sha256": sha256_file(Path(__file__)),
            "evidence_audit_sha256": sha256_file(EQUIPMENT_AUDIT_PATH),
            "final_data_point_evidence_audit_sha256": sha256_file(
                output_dir / "final_data_point_evidence_audit.json"
            ),
            "financial_evidence_audit_sha256": sha256_file(FINANCIAL_AUDIT_PATH),
            "financial_targets_input_sha256": sha256_file(FINANCIAL_TARGETS_PATH),
            "financial_sources_input_sha256": sha256_file(FINANCIAL_SOURCES_PATH),
            "source_traceability_audit_sha256": sha256_file(
                output_dir / "source_traceability_audit.json"
            ),
            "source_direct_excerpt_audit_sha256": sha256_file(
                output_dir / "source_direct_excerpt_audit.json"
            ),
            "factor_public_content_audit_sha256": sha256_file(
                output_dir / "factor_public_content_audit.json"
            ),
            "critical_public_fact_citation_audit_sha256": sha256_file(
                output_dir / "critical_public_fact_citation_audit.json"
            ),
            "target_public_content_audit_sha256": sha256_file(
                output_dir / "target_public_content_audit.json"
            ),
            "anonymized_label_audit_sha256": sha256_file(
                output_dir / "anonymized_label_audit.json"
            ),
        },
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="构建2026—2030硅片制造设备Opportunity Lens研究包")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    pack_path = write_bundle(output_dir=args.output_dir)
    print(pack_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
