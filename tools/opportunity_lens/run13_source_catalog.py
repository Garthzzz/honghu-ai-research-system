from __future__ import annotations

from typing import Any


def _source(
    ref: str,
    title: str,
    publisher: str,
    tier: str,
    status: str,
    excerpt: str,
    fact2: str,
    locator: str,
    independence_key: str,
    published_at: str,
    *,
    channel: str = "web",
    language: str = "zh",
    title_zh: str = "",
    excerpt_zh: str = "",
    rationale: str = "由发布主体直接形成；转载和摘要不另计独立来源。",
    accessed_at: str = "2026-07-22",
    role: str | None = None,
    content_sha256: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "ref": ref,
        "title": title,
        "publisher": publisher,
        "source_tier": tier,
        "source_review_status": status,
        "excerpt": excerpt,
        "language": language,
        "independence_key": independence_key,
        "independence_rationale": rationale,
        "source_channel": channel,
        "published_at": published_at,
        "publish_date": published_at or None,
        "fetch_date": accessed_at,
        "fact2": fact2,
        "policy_evidence_role": role or (
            "weak_signal"
            if status == "weak_source_only"
            else "external_benchmark"
            if channel == "report"
            else "core_evidence"
        ),
    }
    if locator.startswith("http"):
        item["url"] = locator
    else:
        item["local_path"] = locator
    if content_sha256:
        item["content_sha256"] = content_sha256
    if language.startswith("en"):
        item["title_zh"] = title_zh
        item["excerpt_zh"] = excerpt_zh
    return item


SOURCES: list[dict[str, Any]] = [
    # 比亚迪 / 比亚迪电子：官方进度、邻近能力与传闻追溯
    _source(
        "byd_ir_20260330", "比亚迪股份2026年3月投资者关系活动记录", "比亚迪股份", "S", "pass",
        "公司把服务器、液冷、电源和高速互联列入AI基础设施布局，但把电源和高速互联表述为需要加快落地的新产品。",
        "记录没有披露800G、1.6T、OSFP、客户认证、专用产线或光模块收入。",
        "https://static.cninfo.com.cn/finalpage/2026-03-31/1225066866.PDF", "byd_official_ai_infra_202603", "2026-03-30",
    ),
    _source(
        "byde_ar_2025", "比亚迪电子2025年年度报告", "比亚迪电子", "S", "pass",
        "AI算力基础设施收入为9.43亿元，同比增长31.70%，实际进展集中在服务器客户、液冷认证和小批试产、电源研发。",
        "全文没有光模块、800G、1.6T、OSFP或CPO的产品、认证、产能和收入披露，9.43亿元不能归因为光模块。",
        "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0422/2026042200748.pdf", "byde_issuer_2025ar", "2026-04-22",
    ),
    _source(
        "byde_interim_2025", "比亚迪电子2025年中期报告", "比亚迪电子", "S", "pass",
        "报告把AI服务器、液冷、电源管理和高速通信解决方案列为一体化组合。",
        "报告没有公开高速通信所对应的速率、模块形态、传输距离、客户阶段或独立收入。",
        "https://www.byd-electronics.com/material/electronics-official/investor-relations/report/report/cn/250829-c2.pdf", "byde_issuer_2025_interim", "2025-08-29",
    ),
    _source(
        "byde_idce_2026", "比亚迪电子IDCE 2026官方展会回顾", "比亚迪电子", "S", "pass_with_note",
        "官方列出的现场展品是服务器、液冷和电源，英伟达生态伙伴表述对应800VDC高压直流技术。",
        "官方回顾没有列出800G、1.6T光模块、硅光或CPO展品，因此未能为网络文章的光模块展示说法提供旁证；展会回顾可能并非完整展品目录，不能据此断言现场绝对不存在相关展示。",
        "https://www.byd-electronics.com/cn/news/260605.html", "byde_official_idce_2026", "2026-06-04",
    ),
    _source(
        "byde_product_page", "比亚迪电子数据中心产品页", "比亚迪电子", "S", "pass_with_note",
        "当前公开产品页列出通用服务器、存储服务器、AI服务器、热管理、供电和网络方案。",
        "页面没有可核验的800G、1.6T、光模块、CPO、LPO、OSFP或QSFP产品条目；网页缺失不等于内部没有研发。",
        "https://www.byd-electronics.com/cn/product/data-center", "byde_current_product_page", "",
    ),
    _source(
        "byde_history", "比亚迪电子公司介绍与发展历程", "比亚迪电子", "S", "pass",
        "官方里程碑显示2023年开启AI服务器业务，2024年完成数据中心液冷和电源产品布局。",
        "发展历程没有将高速光模块列为已经完成布局、认证或量产的业务。",
        "https://www.byd-electronics.com/cn/about-us", "byde_official_history", "",
    ),
    _source(
        "byd_recruitment_2026", "比亚迪2026届校园招聘简章", "比亚迪", "A", "pass_with_note",
        "集团级电子信息岗位方向包含光通信与光芯片，显示存在相关人才需求。",
        "公开页面没有给出具体用人主体、岗位数量、地点、数据中心产品代际和客户项目，不能直接推断量产准备度。",
        "https://job.byd.com/portal/mobile/schoolSangfor?1wdfb1LbMwhz4TymXhCJbg=%3D", "byd_recruitment_campaign_2026", "",
    ),
    _source(
        "byd_patent_vehicle_1", "基于光通信的车辆系统及车辆", "Google Patents / 比亚迪股份", "S", "pass",
        "CN120415568A的申请人为比亚迪股份，权利要求和实施例明确面向车辆域控制器和车载光网络。",
        "该专利能证明车载光通信邻近研发，不能作为AI数据中心800G或1.6T光模块证明。",
        "https://patents.google.com/patent/CN120415568A/zh", "byd_patent_family_vehicle_2024", "2025-08-01",
    ),
    _source(
        "byd_patent_vehicle_2", "光通信系统和车辆", "Google Patents / 济南比亚迪半导体", "S", "pass",
        "CN121012567A的申请人为济南比亚迪半导体技术有限公司，内容为车载光网关和车辆通信。",
        "申请主体不是比亚迪电子，应用也不是数据中心，不能跨实体或跨场景归因。",
        "https://patents.google.com/patent/CN121012567A/zh", "byd_semiconductor_patent_vehicle", "2025-11-25",
    ),
    _source(
        "byd_patent_vehicle_3", "车辆的通信系统和车辆", "Google Patents / 比亚迪股份", "S", "pass",
        "CN121644261A及同族WO2026045194A1明确属于车辆光通信系统。",
        "检索到的高速光网络相关权利要求仍然面向车辆，未形成数据中心模块的直接专利证据。",
        "https://patents.google.com/patent/CN121644261A/zh", "byd_patent_family_vehicle_2025", "2026-02-26",
    ),
    _source(
        "gov_vehicle_optics_2026", "坪山区车载光通信工作组报道", "深圳市坪山区政府", "S", "pass",
        "比亚迪首席科学家参与的是车载光通信工作组，议题是汽车铜线替代、智能驾驶和座舱网络。",
        "政府侧活动与车载专利形成一致链条，不能被泛化为AI数据中心光模块团队。",
        "https://www.szpsq.gov.cn/zwgk/mtbd/content/post_12856563.html", "gov_vehicle_optical_workgroup_2026", "2026-06-24",
    ),
    _source(
        "byd_firstshanghai_202509", "第一上海比亚迪电子报告", "第一上海", "B", "pass_with_note",
        "报告称公司具备800G产品量产能力、处于客户推广阶段，1.6T正在优化和测试。",
        "这是卖方转述而非公司逐字稿，没有规格、客户、产能、收入和出货证明；只能说明相关研发线索早于2026年7月传闻。",
        "https://pdf.dfcfw.com/pdf/H3_AP202509011737665720_1.pdf", "byde_management_channel_2025h1", "2025-09-01",
        channel="report", role="external_benchmark",
        rationale="卖方报告可能共享同一次管理层沟通底层，与招银国际报告合并为一个证据组，不作为公司直接披露。",
    ),
    _source(
        "byd_cmbi_202511", "招银国际2025年11月策略报告", "招银国际", "B", "pass_with_note",
        "报告称2025年下半年完成800G量产准备、2026年上半年实现1.6T量产。",
        "其底层可能与其他卖方共享管理层沟通，后续公司年报、产品页和展会没有独立确认，不能计作量产事实。",
        "https://www.cmbi.com.hk/upload/202511/20251107738793.pdf", "byde_management_channel_2025h1", "2025-11-07",
        channel="report", role="external_benchmark",
        rationale="卖方报告可能共享同一次管理层沟通底层，与第一上海报告合并为一个证据组，不作为公司直接披露。",
    ),
    _source(
        "byd_weak_rumor_202607", "比亚迪光模块产能与交付传闻文章", "东方财富财富号", "D", "weak_source_only",
        "文章宣称800G月产能、海外交付、1.6T验证和CPO研发，但没有公司原文、规格书、客户文件或产线证据。",
        "这是本轮找到的最早可见成篇版本；后续文章复用相同数字和叙述，只构成一个弱线索簇。比亚迪电子官方IDCE回顾未列光模块，因而没有形成官方旁证。",
        "https://caifuhao.eastmoney.com/news/20260716234716481889230", "weak_rumor_cluster_byd_optics_202607", "2026-07-16",
    ),
    _source(
        "byd_weak_rumor_tgb_20260718", "比亚迪光模块市场传闻的后续转载", "淘股吧", "D", "weak_source_only",
        "文章继续宣称800G月产能、海外交付、1.6T验证和CPO研发，核心数字与7月16日可见版本高度一致。",
        "该页用于记录同源重复和传播路径，不增加独立证据组，也不进入概率、评分或财务输入。",
        "https://www.tgb.cn/a/2twx6gH7TFu-1", "weak_rumor_cluster_byd_optics_202607", "2026-07-18",
        rationale="与7月16日东方财富财富号版本共享相同数字和叙述，判为同一弱线索簇。",
    ),
    _source(
        "byd_wrong_patent_800g", "一种800G光模块", "Google Patents / 苏州卓昱光子", "S", "pass",
        "CN113514924A的申请和权利主体为苏州卓昱光子及亨通相关主体，不是比亚迪。",
        "相似专利搜索结果会造成错误联想，该专利必须从比亚迪技术资产中排除。",
        "https://patents.google.com/patent/CN113514924A/zh", "patent_owner_clarification_800g", "2021-10-19",
    ),
    _source(
        "wuhan_junheng_1p6t_patent", "一种光接收端及1.6T DR8光引擎和耦合方法", "Google Patents / 武汉钧恒", "S", "pass",
        "CN119937105A的申请人为武汉钧恒科技有限公司，权利要求覆盖1.6T DR8光引擎和耦合方法。",
        "该专利能证明武汉钧恒的技术布局，不能归入比亚迪，也不能单独证明武汉钧恒已经规模出货。",
        "https://patents.google.com/patent/CN119937105A/zh", "wuhan_junheng_patent_1p6t_dr8_20250410", "2025-05-06",
    ),
    _source(
        "byd_vehicle_cpo_patent", "比亚迪车辆光通信与光电集成专利", "WIPO / 比亚迪股份", "S", "pass",
        "WO2026045193A1讨论车辆内部光通信、无源光网络以及分立、CPO、2.5D或3D光电集成方式。",
        "专利证明比亚迪具备光通信和CPO概念研发，但技术领域明确属于车辆，不能当作数据中心光模块产品、产能或客户资格。",
        "https://patents.google.com/patent/WO2026045193A1/en", "byd_vehicle_optical_cpo_patent_20240828", "2026-03-05",
    ),
    _source(
        "byd_vehicle_optical_standard", "道路车辆高速光纤线束国家标准计划", "国家市场监督管理总局", "S", "pass",
        "国家标准计划20253391-T-339面向最高100Gbit/s车载光纤线束，比亚迪汽车工业有限公司列入起草单位。",
        "标准参与增强车载光通信证据，但与数据中心800G/1.6T的产品和资格体系不是同一市场。",
        "https://std.samr.gov.cn/gb/search/gbDetailed?id=3BD7197C4E7FA3E7E06397BE0A0A94C7", "byd_vehicle_optical_standard_20253391", "2025-08-06",
    ),
    _source(
        "byd_vertilite_stake", "纵慧芯光股东结构披露", "东阳光 / 中国证券报", "S", "pass_with_note",
        "公告列示比亚迪股份持有VCSEL芯片企业纵慧芯光1.121%股权。",
        "小比例股权只能证明上游产业联系，未披露供货协议、排他合作、产能预留或800G/1.6T认证，不能写成锁定光芯片供应。",
        "https://epaper.cs.com.cn/zgzqb/images/2025-06/18/B011/zqB01118.pdf", "vertilite_shareholder_disclosure_20250618", "2025-06-18",
    ),

    # 立讯：公司披露、客户/供应商侧证据、专利与反证
    _source(
        "luxshare_ar_2025", "立讯精密2025年年度报告", "立讯精密", "S", "pass",
        "年报确认DPO、LPO、LRO光模块和AOC覆盖至1.6T；800G、1.6T已有小批量供货，800G LRO获部分客户验证。",
        "年报同时显示1.6T部分路线仍在研发验证，客户未具名，不能把小批量写成全球头部客户规模份额。",
        "https://static.cninfo.com.cn/finalpage/2026-04-15/1225104908.PDF", "luxshare_issuer_2025ar", "2026-04-15",
    ),
    _source(
        "luxshare_ar_2024", "立讯精密2024年年度报告", "立讯精密", "S", "pass_with_note",
        "公司称800G硅光模块通过头部AI智算中心客户测试，并向多家国际客户量产交付；1.6T采用Marvell DSP。",
        "后续2025年报仍使用小批量口径，说明2024表述可能只对应特定SKU或项目，不能外推整个业务规模。",
        "https://static.cninfo.com.cn/finalpage/2025-04-26/1223326862.PDF", "luxshare_issuer_2024ar", "2025-04-26",
    ),
    _source(
        "luxshare_ir_20250428", "立讯精密2025年4月投资者关系记录", "立讯精密", "S", "pass",
        "公司称800G硅光模块处于量产、1.6T正在客户验证，并计划投资核心器件和高度自动化光模块工厂。",
        "记录未披露工厂地址、设备、有效产能、良率、客户数和收入。",
        "https://static.cninfo.com.cn/finalpage/2025-04-28/1223359128.PDF", "luxshare_ir_20250428", "2025-04-28",
    ),
    _source(
        "luxshare_ir_20260507", "立讯精密2026年5月业绩说明交流", "立讯精密", "S", "pass",
        "公司明确光模块业务才起步，相对市场规模仍很小。",
        "投资者提问中的约3亿元和0.1%占比没有获得公司确认，不能作为财务输入。",
        "https://static.cninfo.com.cn/finalpage/2026-05-07/1225280960.PDF", "luxshare_ir_20260507", "2026-05-07",
    ),
    _source(
        "luxshare_ir_20260525", "立讯精密2025年度股东会交流记录", "立讯精密", "S", "pass",
        "公司没有回答已有多少CSP完成验证和量产，明确称自己是光模块新进入者，商务和营收规模拓展仍需时间。",
        "公司同时确认目前不具备自研1.6T硅光芯片能力，通信和数据中心新业务前置投入短期拉低毛利率。",
        "https://static.cninfo.com.cn/finalpage/2026-05-25/1225328100.PDF", "luxshare_ir_20260525", "2026-05-25",
    ),
    _source(
        "luxshare_interactive_20260428", "立讯精密关于光模块商业化进度的互动易答复", "立讯精密答复 / 同花顺iNews镜像", "A", "pass_with_note",
        "公司答复光模块仍处技术培育和导入早期、尚未完成商业转化，2025年收入占比约0.1%，与北美头部CSP仍在早期接洽。",
        "公司同时明确否认“北美客户1000万只光模块订单”。链接保存了逐字公司答复，但仍是媒体对互动易内容的镜像；0.1%与订单否认按强线索使用，规模判断同时由公司后续正式交流中“业务才起步、规模很小”的表述约束。",
        "https://news.10jqka.com.cn/20260428/c676349118.shtml", "luxshare_irm_reply_20260428", "2026-04-28",
        rationale="同花顺iNews逐字镜像立讯在交易所互动平台的公司答复；其他媒体转载共享同一底层回复，只计一个证据组。因缺直接互动易固定链接，证据级别由S降为A并与正式投资者交流交叉使用。",
    ),
    _source(
        "luxshare_ir_20251126", "立讯精密2025年11月投资者关系记录", "立讯精密", "S", "pass",
        "公司解释光模块依赖Broadcom、Marvell等核心光电器件，自己更多承担后端模组组装、光对准和自动调测。",
        "该价值链位置有利于制造切入，但外购DSP、光引擎和激光器会限制垂直整合与利润捕获。",
        "https://static.cninfo.com.cn/finalpage/2025-11-26/1224827335.PDF", "luxshare_ir_20251126", "2025-11-26",
    ),
    _source(
        "luxshare_ir_20250828", "立讯精密2025年8月投资者交流记录", "立讯精密", "S", "pass",
        "公司称800G硅光模块实现量产、1.6T处于客户验证，同时明确800G和1.6T主要向中小型数据中心客户交付，尚未获得头部客户明确商务合作机会。",
        "“量产”与“头部CSP规模份额”不是同一事件；该记录支持中小客户商业化，也直接限制全球头部客户概率。",
        "https://static.cninfo.com.cn/finalpage/2025-08-29/1224617071.PDF", "luxshare_ir_20250828", "2025-08-28",
    ),
    _source(
        "luxshare_ir_20260420", "立讯精密2026年4月投资者关系记录", "立讯精密", "S", "pass_with_note",
        "公司称铜光互连、散热和电源产品在国内外客户取得进展，并表示NPO存在明确商业机会。",
        "记录没有给出客户名称、光模块验证数量、订单、收入和复购，不能把“进展顺利”提升为头部CSP资格完成。",
        "https://static.cninfo.com.cn/finalpage/2026-04-20/1225126250.PDF", "luxshare_ir_20260420", "2026-04-20",
    ),
    _source(
        "luxshare_product_matrix", "Luxshare-Tech optical transceiver product matrix", "Luxshare-Tech", "A", "pass_with_note",
        "The official page lists DPO, LRO and LPO optical modules from 10G to 1.6T in SFP, QSFP, QSFP-DD and OSFP form factors.",
        "A product page demonstrates portfolio readiness but does not disclose CSP qualification, repeat orders, yield, capacity or revenue.",
        "https://en.luxshare-tech.com/products/optics/transceivers_2.html", "luxshare_product_marketing_matrix", "",
        language="en", title_zh="Luxshare-Tech光收发模块产品矩阵", excerpt_zh="官网列出覆盖10G至1.6T的DPO、LRO和LPO模块，形态包括SFP、QSFP、QSFP-DD和OSFP；产品页不等于客户认证。",
    ),
    _source(
        "luxshare_ofc_2025", "Luxshare Tech showcases 1.6T and 800G solutions at OFC 2025", "Luxshare-Tech", "A", "pass_with_note",
        "Luxshare demonstrated 1.6T and 800G modules and an 800G link with a Juniper switch and Keysight test equipment.",
        "The demonstration verifies engineering interoperability at the booth, not long-duration CSP qualification or an approved vendor list.",
        "https://en.luxshare-tech.com/company/resources/news/luxshare-tech-showcases-breakthrough-1.6t-and-800g-solutions-at-ofc-2025.html", "luxshare_ofc2025_demo", "2025-04-02",
        language="en", title_zh="立讯在OFC 2025展示1.6T与800G方案", excerpt_zh="立讯展示1.6T和800G模块，并与Juniper交换机和Keysight测试设备完成800G链路演示；展台互通不等于客户资格。",
    ),
    _source(
        "luxshare_ofc_2026", "OFC 2026 Preview - Luxshare-Tech is Enabling Next-Gen Optical Interconnects and High-Speed Solutions", "Luxshare-Tech", "A", "pass_with_note",
        "Luxshare-Tech announced OFC 2026 live demonstrations for 1.6T interconnects and a 12.8T liquid-cooled XPO optical module, and joined OIF multi-vendor demonstrations covering CEI-224G/448G and co-packaging.",
        "This is current official evidence of continued product and architecture development, but a trade-show preview does not establish named CSP qualification, repeat orders, dedicated capacity, yield or revenue.",
        "https://en.luxshare-tech.com/company/resources/news/ofc-2026-preview.html", "luxshare_ofc2026_official_product", "",
        language="en", title_zh="立讯OFC 2026高速互连与XPO展示", excerpt_zh="立讯官网预告OFC 2026将展示1.6T互连、12.8T液冷XPO光模块并参加OIF多厂商互操作，证明产品与新架构研发延续；展会展示不等于头部云客户资格、复购或规模收入。",
    ),
    _source(
        "keysight_luxshare_ofc2024", "Empowering tomorrow's Ethernet networks", "Keysight", "A", "pass",
        "Keysight independently documented BER, pre-FEC BER and FEC-margin demonstrations using Luxshare 800G OSFP 2xDR4, 2xFR4 and QSFP-DD AOC modules.",
        "This independently supports a working module and interoperability, but not CSP reliability approval or purchase volume.",
        "https://www.keysight.com/blogs/en/inds/ai/empowering-tomorrows-ethernet-networks", "keysight_ofc2024_luxshare_demo", "2024-04-01",
        language="en", title_zh="Keysight记录立讯800G联合演示", excerpt_zh="Keysight独立记录立讯800G模块的误码率、纠错前误码率和FEC余量演示，证明模块可工作但不证明云厂资格。",
    ),
    _source(
        "oif_luxshare_2024", "OIF CEI interoperability demo report at OFC 2024", "OIF", "A", "pass",
        "The OIF test matrix lists a Luxshare DR8 module in a CEI-112G linear multi-vendor interoperability demonstration.",
        "Standards interoperability is below supplier qualification, product-code approval and sustained volume orders.",
        "https://www.oiforum.com/wp-content/uploads/OIF_CEI_Demo_OFC2024_Final.pdf", "oif_ceilinear_2024", "2024-04-01",
        language="en", title_zh="OIF 2024多厂商互操作演示报告", excerpt_zh="OIF测试矩阵列出立讯DR8模块参与CEI-112G线性多厂商互操作；标准互通仍低于供应商认证和批量订单。",
    ),
    _source(
        "poet_luxshare_2024", "POET and Luxshare Tech expand AI-network product offerings", "POET Technologies", "A", "pass",
        "POET confirmed an 800G 2xFR4 OSFP collaboration using its receive optical engine, with Luxshare responsible for manufacturing and global sales.",
        "The supplier-side confirmation proves a real product collaboration but does not disclose final customer qualification or procurement volume.",
        "https://www.poet-technologies.com/news/poet-and-luxshare-tech-expand-product-offerings-for-artificial-intelligence-networks", "supplier_poet_luxshare_2024", "2024-08-01",
        language="en", title_zh="POET与立讯扩大AI网络产品合作", excerpt_zh="POET确认双方合作800G 2xFR4 OSFP，立讯负责制造和全球销售；供应商确认不等于终端客户资格。",
    ),
    _source(
        "poet_anonymous_order_boundary", "POET 2025 production order and 2026 annual filing", "POET Technologies / SEC", "S", "pass",
        "POET disclosed a $5 million 800G optical-engine production order from an unnamed leading systems integrator; later filings did not identify Luxshare as that customer.",
        "The order must not be attributed to Luxshare, Meta or another named customer. POET separately confirms a design-in to Luxshare modules, which proves engineering integration but not the anonymous order's buyer.",
        "https://www.sec.gov/Archives/edgar/data/1437424/000149315226014253/form20-f.htm", "poet_anonymous_order_boundary_2026", "2026-04-01",
        language="en", title_zh="POET匿名800G订单与立讯合作的归因边界", excerpt_zh="POET披露500万美元800G光引擎订单，但客户匿名；监管文件没有把该订单归给立讯。另有立讯模块design-in证据，二者不能合并。",
    ),
    _source(
        "luxshare_us_optical_recruitment", "Lead Optical Engineer recruitment in Milpitas", "Luxshare-Tech", "A", "pass_with_note",
        "The role covers 400G/800G/1.6T, customer qualification, EVT-to-MP, EML/DML/PD/VCSEL/SiPh, DSP/driver/TIA and reliability tests including HTOL, THB and temperature cycling.",
        "The posting supports expansion of US engineering and qualification capability, but recruitment intent is not completed qualification, yield or a customer award.",
        "https://www.linkedin.com/jobs/view/optical-engineer-at-luxshare-tech-4403561166", "luxshare_us_recruitment_2026", "",
        language="en", title_zh="立讯美国光模块首席光学工程师招聘", excerpt_zh="岗位覆盖400G/800G/1.6T、客户认证、从工程验证到量产、核心器件与可靠性测试，说明美国工程能力在建设；招聘不等于已获客户订单。",
    ),
    _source(
        "xinqiang_supplier_ipo", "欣强电子上市保荐书", "深圳证券交易所 / 欣强电子", "S", "pass",
        "文件称2024年800G和1.6T光模块PCB实现批量供货，主要客户包括东莞讯滔，相关PCB收入1.29亿元。",
        "终端客户名单是多个PCB客户用途的汇总，不能逐一映射为讯滔或立讯的CSP客户。",
        "https://reportdocs.static.szse.cn/UpFiles/rasinfodisc1/202506/RAS_202506_3021059C895CB837B441829FED0802BC73026D.pdf", "supplier_xinqiang_ipo_2024", "2025-06-30",
    ),
    _source(
        "nvidia_connectx8_list", "Validated and supported cables and switches for ConnectX-8", "NVIDIA", "S", "pass_with_note",
        "The February 2026 list names several 800G optical-module vendors, while Luxshare appears for a 200G DAC but not an 800G optical module.",
        "The absence only constrains this platform and revision; it prevents rewriting Luxshare's compatibility test as NVIDIA public optical qualification.",
        "https://networking-docs.nvidia.com/connectx8fwrn/40481000/validated-and-supported-cables-and-switches", "nvidia_connectx8_validation_2026", "2026-02-16",
        language="en", title_zh="NVIDIA ConnectX-8验证与支持清单", excerpt_zh="清单列出多家800G光模块厂商，立讯只出现在200G铜缆条目；该反证仅约束这一平台和版本。",
    ),
    _source(
        "luxshare_siph_gov_project", "东莞市重点领域研发项目库", "东莞市科学技术局", "S", "pass",
        "项目库列入东莞立讯技术承担的硅光芯片及3D光电混合封装设计和应用项目。",
        "项目证明系统性研发投入，但项目名称不能证明1.6T硅光芯片已经自研量产。",
        "https://dgstb.dg.gov.cn/attachment/0/314/314210/4332212.pdf", "dgstb_siph_project_2023", "2024-01-01",
    ),
    _source(
        "luxshare_patent_cpo", "共封装集成光电模块及交换芯片结构", "Google Patents / 东莞立讯技术", "S", "pass",
        "CN113917631A/B及美台同族覆盖交换ASIC周边共封装光电模块、电源和监控结构。",
        "授权专利证明CPO研发连续性和跨国布局，不证明客户订单、良率或量产。",
        "https://patents.google.com/patent/CN113917631A/zh", "luxshare_patent_family_cpo_2021", "2022-01-11",
    ),
    _source(
        "luxshare_patent_sipho", "Optical module with silicon-photonic chip and external laser", "Google Patents / Dongguan Luxshare", "S", "pass",
        "US12248173B2 and CN114815089B cover a silicon-photonic chip, external laser, metal base and thermal path.",
        "The patent supports module packaging and thermal design, not in-house fabrication of the silicon-photonic chip.",
        "https://patents.google.com/patent/US12248173B2/en", "luxshare_patent_family_sipho_2022", "2025-03-11",
        language="en", title_zh="立讯硅光芯片外置激光光模块专利", excerpt_zh="专利涉及硅光芯片、外置激光、金属基座与散热路径，支持封装设计能力但不等于自制硅光芯片。",
    ),
    _source(
        "luxshare_patent_tx", "光发射组件和光模块", "Google Patents / 东莞立讯技术与东莞讯滔", "S", "pass",
        "CN115755292B涉及合波器和光发射组件散热，由东莞立讯技术与东莞讯滔共同申请。",
        "2026年授权说明母子公司技术资产连续，但授权本身不是量产或客户认证证据。",
        "https://patents.google.com/patent/CN115755292B/zh", "luxshare_patent_family_tx_2022", "2026-03-20",
    ),

    # 行业需求、标准、上游约束、竞争者与龙头
    _source(
        "lightcounting_jan2026", "AI creates a new wave in demand for optical transceivers", "LightCounting", "A", "pass",
        "LightCounting estimates AI-cluster Ethernet optics and CPO sales at $16.5 billion in 2025 and $26 billion in 2026, about 60% growth in each year.",
        "The research also says VCSEL and InP laser shortages constrained shipments, so demand forecasts cannot be treated as immediately deliverable revenue.",
        "https://www.lightcounting.com/newsletter/en/january-2026-optics-for-ai-clusters-366", "lightcounting_ai_optics_jan2026", "2026-01-01",
        language="en", title_zh="AI推动光模块需求并加速CPO", excerpt_zh="LightCounting估计AI集群以太网光模块与CPO市场2025年165亿美元、2026年260亿美元；VCSEL与InP激光器短缺曾限制出货。",
    ),
    _source(
        "lightcounting_apr2026", "Demand for optical connectivity continues to surprise", "LightCounting", "A", "pass",
        "Ethernet transceiver sales grew 93% in 2024 and an estimated 82% in 2025; the 2026 forecast is 65% growth.",
        "Demand exceeded InP EML and laser supply by roughly 30%, but shortages were expected to ease by end-2026, raising a later price-normalization risk.",
        "https://www.lightcounting.com/newsletter/en/april-2026-market-forecast-379", "lightcounting_market_apr2026", "2026-04-01",
        language="en", title_zh="光连接需求继续超预期", excerpt_zh="LightCounting预计2026年以太网光模块增长65%，当前需求比InP EML和激光器供给高约30%，短缺可能在2026年末缓解。",
    ),
    _source(
        "lightcounting_feb2026", "AI capex flows down the supply chain to DSP vendors", "LightCounting", "A", "pass",
        "The research expects 800G shipments to more than double in 2026 and 1.6T to grow from a small 2025 base to tens of millions of ports.",
        "The figures are an industry forecast, not completed shipments or named-customer orders.",
        "https://lightcounting.com/newsletter/en/february-2026-pam4-and-coherent-dsps-updated-april-2026-381", "lightcounting_dsp_feb2026", "2026-02-26",
        language="en", title_zh="AI资本开支向光模块DSP传导", excerpt_zh="LightCounting预计2026年800G出货翻倍以上，1.6T由小基数增至数千万端口；这是预测而不是已完成出货。",
    ),
    _source(
        "trendforce_optics_202604", "2026 AI optical-module market outlook", "TrendForce", "A", "pass",
        "TrendForce estimates the AI optical-module market at $16.5 billion in 2025 and $26 billion in 2026, while identifying EML, CW lasers, precision alignment and thermal design as bottlenecks.",
        "The forecast identifies 2026-2027 as a 1.6T design-in window but does not certify any supplier's customer status.",
        "https://www.trendforce.com/presscenter/news/20260420-13017.html", "trendforce_optics_apr2026", "2026-04-20",
        language="en", title_zh="TrendForce 2026年AI光模块市场展望", excerpt_zh="机构估计AI光模块市场2025年165亿美元、2026年260亿美元，并指出EML、CW激光、精密对准和散热是瓶颈。",
    ),
    _source(
        "trendforce_google_202602", "800G-and-above optical-module demand for AI infrastructure", "TrendForce", "A", "pass_with_note",
        "TrendForce estimates 800G-and-above shipment share above 60% in 2026 and models Google TPU demand at roughly four million accelerators and over six million modules.",
        "The Google and supplier-share figures are analyst estimates, not Google procurement disclosures.",
        "https://www.trendforce.com/presscenter/news/20260210-12919.html", "trendforce_google_arch_feb2026", "2026-02-10",
        language="en", title_zh="800G以上AI光模块需求预测", excerpt_zh="TrendForce预计2026年800G以上出货占比超过60%，并估算Google TPU与模块需求；客户与份额数字不是Google官方采购披露。",
    ),
    _source(
        "trendforce_laser_capacity_202606", "AI data-center expansion to double EML and CW-DFB laser capacity in 2026", "TrendForce", "A", "pass_with_note",
        "TrendForce estimates combined EML and CW-DFB laser monthly capacity at about 50.7 million units in 2026, roughly double the prior level, with Broadcom, Lumentum and Sumitomo Electric accounting for an estimated 55%.",
        "The unit is a laser-device capacity forecast, not qualified optical-module output. It cannot be added to module capacity or allocated to a new entrant without yield, customer qualification and supply-allocation evidence.",
        "https://www.trendforce.com/presscenter/news/20260603-13077.html", "trendforce_laser_capacity_jun2026", "2026-06-03",
        language="en", title_zh="TrendForce预计2026年EML与CW-DFB激光器产能翻倍", excerpt_zh="TrendForce预计2026年EML与CW-DFB激光器合计月产能约5070万只、约为此前两倍；这是激光器件预测，不能直接当成合格光模块产能。",
    ),
    _source(
        "microsoft_fy26q3", "Microsoft FY2026 Q3 earnings", "Microsoft", "S", "pass",
        "Microsoft expects calendar-2026 capex of about $190 billion and remained capacity-constrained through 2026.",
        "Cloud capex is a demand ceiling, not optical-module revenue; servers, buildings, power and networking must be separated.",
        "https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q3", "microsoft_ir_fy26q3", "2026-04-29",
        language="en", title_zh="微软2026财年第三季度业绩", excerpt_zh="微软预计2026自然年资本开支约1900亿美元，并称2026年仍受容量约束；资本开支不能直接等同光模块收入。",
    ),
    _source(
        "alphabet_2025q4", "Alphabet 2025 Q4 and fiscal-year results", "Alphabet", "S", "pass",
        "Alphabet guided 2026 capex to $175-185 billion; its 2025 mix was described as roughly 60% servers and 40% data centers and networking.",
        "The 40% category combines buildings and networking, so it still cannot be assigned wholly to optical modules.",
        "https://abc.xyz/investor/news/news-details/2026/Alphabet-Announces-Fourth-Quarter-2025-and-Fiscal-Year-Results-2026-KEvZIMKBLS/default.aspx", "alphabet_ir_2025q4", "2026-02-04",
        language="en", title_zh="Alphabet 2025年第四季度及全年业绩", excerpt_zh="Alphabet指引2026年资本开支1750亿至1850亿美元；2025年约60%用于服务器、40%用于数据中心和网络。",
    ),
    _source(
        "amazon_2025q4", "Amazon fourth-quarter 2025 results", "Amazon", "S", "pass",
        "Amazon expects about $200 billion of 2026 capex, largely for AI and AWS infrastructure.",
        "The group capex figure includes facilities, compute, logistics and other investments and is not a transceiver purchase figure.",
        "https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Fourth-Quarter-Results/default.aspx", "amazon_ir_2025q4", "2026-02-05",
        language="en", title_zh="亚马逊2025年第四季度业绩", excerpt_zh="亚马逊预计2026年资本开支约2000亿美元，主要支持AI与AWS；集团资本开支不是光模块采购额。",
    ),
    _source(
        "meta_2026q1", "Meta first-quarter 2026 results", "Meta", "S", "pass",
        "Meta raised its 2026 capex range to $125-145 billion.",
        "The capex signal supports AI-infrastructure demand but must be converted through network architecture and optical-port intensity.",
        "https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/", "meta_ir_2026q1", "2026-04-29",
        language="en", title_zh="Meta 2026年第一季度业绩", excerpt_zh="Meta把2026年资本开支指引上调至1250亿至1450亿美元；需要经过网络架构和端口强度才能映射到光模块。",
    ),
    _source(
        "alibaba_ai_2025", "Alibaba to invest at least RMB380 billion in cloud and AI infrastructure", "Alibaba", "S", "pass",
        "Alibaba announced at least RMB380 billion of cloud and AI-infrastructure investment over three years.",
        "The commitment supports Chinese demand but does not identify optical-module vendors or procurement quantities.",
        "https://alihome.alibaba-inc.com/en-US/document-1830678592242057216", "alibaba_ai_investment_2025", "2025-02-24",
        language="en", title_zh="阿里未来三年投入至少3800亿元建设云和AI基础设施", excerpt_zh="阿里宣布未来三年至少投入3800亿元建设云和AI基础设施；承诺不包含光模块供应商和采购量。",
    ),
    _source(
        "ethernet_alliance_2026", "OFC 2026: the technical lead's perspective", "Ethernet Alliance", "A", "pass",
        "More than half of participants brought 1.6T hosts or optics; retimed, LPO, LRO and FRO architectures showed different reach, power and margin trade-offs.",
        "Multi-vendor interoperability demonstrates ecosystem progress but is below CSP production qualification.",
        "https://ethernetalliance.org/blog/2026/05/27/ofc-2026-the-tech-leads-perspective/", "ethernet_alliance_ofc2026", "2026-05-27",
        language="en", title_zh="OFC 2026多厂商以太网互操作观察", excerpt_zh="超过半数参与者带来1.6T主机或光模块，不同线性和重定时架构存在距离、功耗与余量权衡；互通仍低于客户量产资格。",
    ),
    _source(
        "ethernet_alliance_qualification", "800G from lab evaluation to field deployment", "Ethernet Alliance", "A", "pass",
        "The deployment path moves from silicon and FPGA validation through vendor trials, beta samples, interoperability, manufacturing and commercial release.",
        "This staged path shows why a patent, product page or booth demonstration cannot jump directly to sustainable production revenue.",
        "https://ethernetalliance.org/blog/2024/04/25/800g-from-lab-evaluation-to-field-deployment/", "ethernet_alliance_lab_to_deploy", "2024-04-25",
        language="en", title_zh="800G从实验室评估到现场部署", excerpt_zh="部署路径依次经过芯片/FPGA验证、供应商试验、测试样品、互操作、制造和商业发布，不能从专利或展会直接跳到收入。",
    ),
    _source(
        "fabrinet_qualification", "Fabrinet fiscal 2025 Form 10-K", "Fabrinet / SEC", "S", "pass",
        "Manufacturing process and site qualification commonly takes three to six months or longer, followed by test runs and orders, and must satisfy both direct customers and their customers.",
        "The disclosure supports a two-layer qualification concept: manufacturing-process approval plus platform or end-customer product approval.",
        "https://www.sec.gov/Archives/edgar/data/1408710/000140871025000039/fn-20250627.htm", "fabrinet_10k_qualification_2025", "2025-08-18",
        language="en", title_zh="Fabrinet 2025财年年报的客户资格流程", excerpt_zh="制程和工厂资格通常需要三至六个月或更久，之后才有测试批和订单，并要同时满足直接客户及其客户要求。",
    ),
    _source(
        "oif_ofc2026", "OIF validates interoperability live at OFC 2026", "OIF", "A", "pass",
        "Forty firms participated in CEI-224G/448G, co-packaging and CMIS interoperability, including Luxshare-Tech and incumbent optical vendors.",
        "Participation proves ecosystem engagement and interoperability activity, not any named cloud customer's approved-vendor status.",
        "https://www.oiforum.com/oif-validates-critical-interoperability-live-at-ofc-2026-through-multi-vendor-demonstrations-and-expert-panels/", "oif_ofc2026_interop", "2026-03-18",
        language="en", title_zh="OIF在OFC 2026进行多厂商互操作验证", excerpt_zh="40家公司参与CEI-224G/448G、共封装和CMIS互操作，其中包括立讯和多家龙头；参与不等于云厂资格。",
    ),
    _source(
        "ieee_8023df", "IEEE 802.3df-2024 800 Gb/s Ethernet", "IEEE", "S", "pass",
        "IEEE 802.3df-2024 is an active standard for 800 Gb/s Ethernet.",
        "An active interface standard defines technical compatibility but does not certify an individual supplier's quality, yield or customer approval.",
        "https://standards.ieee.org/standard/802_3df-2024.html", "ieee_8023df_2024", "2024-01-01",
        language="en", title_zh="IEEE 802.3df-2024 800Gb以太网标准", excerpt_zh="IEEE 802.3df-2024是有效的800Gb以太网标准；接口标准不认证单个供应商的质量、良率或客户资格。",
    ),
    _source(
        "ieee_p8023dj", "IEEE P802.3dj 200 Gb/s per lane task force", "IEEE 802.3", "S", "pass_with_note",
        "As of July 2026, P802.3dj for 200 Gb/s per lane and 1.6TbE remained in the task-force, draft and ballot process.",
        "Suppliers can ship to MSA or draft specifications, but public text should not call 1.6TbE a fully final IEEE standard yet.",
        "https://www.ieee802.org/3/dj/", "ieee_p8023dj_status_202607", "2026-07-22",
        language="en", title_zh="IEEE P802.3dj每通道200Gb任务组", excerpt_zh="截至2026年7月，1.6TbE相关P802.3dj仍处在任务组、草案和投票流程；厂商可按MSA或草案出货，但不能称正式标准已完成。",
    ),
    _source(
        "coherent_capacity_2026", "Coherent OFC 2026 investor presentation", "Coherent", "S", "pass",
        "Coherent said it was on track to double internal InP output in 2026 and more than double it again by 2027.",
        "Announced capacity still requires installation, yield ramp and customer allocation before it becomes qualified module supply.",
        "https://www.coherent.com/content/dam/coherent/site/en/documents/investors/investor-presentations/2026/march-17/OFC-2026-Investor%20event-deck-vf.pdf", "coherent_inp_capacity_2026", "2026-03-17",
        language="en", title_zh="Coherent OFC 2026投资者材料", excerpt_zh="Coherent计划2026年把内部InP产出翻倍、2027年再增加一倍以上；扩产仍需安装、良率爬坡和客户分配。",
    ),
    _source(
        "veeco_inp_orders_2026", "Veeco announces $250 million in InP-laser equipment orders", "Veeco", "S", "pass",
        "Veeco disclosed more than $250 million of multi-customer equipment orders for InP lasers, with deliveries starting in 2026 and accelerating in 2027.",
        "Equipment orders independently confirm a bottleneck and expansion cycle, but they lead effective qualified supply by installation and yield-ramp time.",
        "https://ir.veeco.com/news-and-events/news-details/2026/Veeco-Announces-250-Million-in-Equipment-Orders-for-Manufacturing-Indium-Phosphide-Lasers/default.aspx", "veeco_inp_orders_2026", "2026-05-05",
        language="en", title_zh="Veeco获得2.5亿美元InP激光器设备订单", excerpt_zh="Veeco披露多客户InP激光器设备订单超过2.5亿美元，2026年开始交付、2027年加速；设备订单领先于有效供给。",
    ),
    _source(
        "aixtron_lumentum_2026", "AIXTRON receives multiple 6-inch InP MOCVD orders from Lumentum", "AIXTRON", "S", "pass",
        "Lumentum ordered multiple G10-AsP systems for 6-inch InP production supporting 800G-and-above AI optical solutions.",
        "The order confirms capacity expansion but not the exact timing, yield or allocation available to new module entrants.",
        "https://aixtron.com/en/press/press-releases/AIXTRON%20receives%20multiple%20orders%20for%20G10-AsP%20MOCVD%20Systems%20from%20Lumentum%20to%20support%20expansion%20of%20High-Speed%20Optical%20Solutions%20for%20AI%20Networks_n13987", "aixtron_lumentum_inp_2026", "2026-05-19",
        language="en", title_zh="AIXTRON获得Lumentum多台6英寸InP设备订单", excerpt_zh="Lumentum订购多台6英寸InP MOCVD设备，服务800G以上AI光学方案；订单不等于立即形成可分配给新进入者的合格产能。",
    ),
    _source(
        "nvidia_coherent_2026", "NVIDIA and Coherent strategic optics partnership", "NVIDIA / Coherent", "S", "pass",
        "NVIDIA invested $2 billion and entered a nonexclusive multiyear purchase commitment and capacity-rights agreement with Coherent.",
        "The agreement demonstrates upstream scarcity and customer capacity locking; nonexclusive must not be rewritten as sole-source status.",
        "https://www.coherent.com/news/press-releases/nvidia-and-coherent-announce-strategic-partnership", "nvidia_coherent_commitment_2026", "2026-03-02",
        language="en", title_zh="NVIDIA与Coherent建立光学战略合作", excerpt_zh="NVIDIA投资20亿美元并签订非排他、多年采购承诺和产能权协议，证明上游稀缺和锁产，但不是独家。",
    ),
    _source(
        "nvidia_cpo_202607", "Vera Rubin and Spectrum-X Photonics enter volume manufacturing", "NVIDIA", "S", "pass",
        "NVIDIA said Spectrum-X Ethernet Photonics co-packaged-optics switches had entered volume manufacturing, with initial adopters including CoreWeave, Lambda and OCI.",
        "CPO therefore is no longer only a roadmap risk, but it replaces pluggables first in specified switch layers rather than the whole optical market at once.",
        "https://blogs.nvidia.com/blog/vera-rubin/", "nvidia_cpo_volume_202607", "2026-07-21",
        language="en", title_zh="Vera Rubin与Spectrum-X光子交换机进入批量制造", excerpt_zh="NVIDIA称Spectrum-X CPO交换机已进入批量制造，首批采用者包括CoreWeave、Lambda和OCI；CPO先替代特定交换层端口。",
    ),
    _source(
        "nvidia_cpo_pluggable_coexist", "NVIDIA Spectrum-X co-packaged-optics switches for AI factories", "NVIDIA", "S", "pass",
        "NVIDIA's announcement identifies a CPO ecosystem while also naming Coherent, Eoptolink, Fabrinet and Innolight as pluggable-transceiver supporters.",
        "The evidence supports coexistence and a value-chain shift, not an immediate disappearance of pluggable optics.",
        "https://nvidianews.nvidia.com/news/nvidia-spectrum-x-co-packaged-optics-networking-switches-ai-factories/", "nvidia_cpo_pluggable_coexist", "2025-03-18",
        language="en", title_zh="NVIDIA CPO交换机与可插拔光模块生态", excerpt_zh="NVIDIA同时列出CPO生态和中际、新易盛等可插拔支持方，支持并存和价值链迁移而非可插拔立即消失。",
    ),
    _source(
        "aaoi_1p6t_order", "AOI receives first volume order for 1.6T data-center transceivers", "Applied Optoelectronics", "S", "pass",
        "AOI received a first 1.6T volume order from a long-standing hyperscale customer and targeted combined 800G/1.6T monthly capacity above 500,000 units by end-2026.",
        "The customer remains unnamed and planned capacity still requires ramp execution, but this is stronger commercial evidence than a demo or product page.",
        "https://investors.ao-inc.com/news-releases/news-release-details/aoi-receives-first-volume-order-16t-data-center-transceivers", "aaoi_1p6t_volume_order_2026", "2026-03-09",
        language="en", title_zh="AOI获得首个1.6T数据中心光模块批量订单", excerpt_zh="AOI获得长期超大规模客户的首个1.6T批量订单，计划2026年底800G与1.6T合计月产能超过50万只；客户未具名且产能仍需爬坡。",
    ),
    _source(
        "foxconn_q1_2026", "Hon Hai first-quarter 2026 results", "Hon Hai / Foxconn", "S", "pass_with_note",
        "Foxconn said CPO and 1.6T high-end switching products were under joint development with major cloud and AI customers and preparing for production, with shipments expected from Q3 2026.",
        "The disclosure mixes switches, modules and optoelectronic integration and therefore cannot be rewritten as a named CSP optical-module approval.",
        "https://www.honhai.com/en-us/press-center/press-releases/latest-news/2018", "foxconn_q1_2026_optics", "2026-05-14",
        language="en", title_zh="鸿海2026年第一季度业绩中的1.6T与CPO进展", excerpt_zh="鸿海称CPO和1.6T高端交换产品与主要云及AI客户共研并准备量产，预计2026年第三季度出货；不能等同具名CSP光模块资格。",
    ),
    _source(
        "jabil_1p6t_2025", "Jabil launches 1.6T pluggable transceiver", "Jabil", "S", "pass_with_note",
        "Jabil launched 1.6T DR8, DR8+ and 2xFR4 products using an Intel silicon-photonics engine and demonstrated them at OFC 2025.",
        "A mature product table and demo do not establish named-customer volume orders, yield or sustained market share.",
        "https://www.jabil.com/news/jabil-launches-1.6t-pluggable-transceiver.html", "jabil_1p6t_launch_2025", "2025-03-31",
        language="en", title_zh="Jabil发布1.6T可插拔光模块", excerpt_zh="Jabil基于Intel硅光引擎发布1.6T DR8、DR8+和2xFR4产品并在OFC展示；仍缺具名客户批量订单。",
    ),
    _source(
        "accelink_ir_20260514", "光迅科技2025年度业绩说明会记录", "光迅科技", "S", "pass",
        "公司称1.6T产品已具备批量交付能力，800G出货占比上升，3.2T硅光单模NPO已在国内头部CSP完成系统验证。",
        "公司没有披露1.6T实际出货、客户、良率和产能；DSP外购、硅光流片外包，因此“具备能力”不能直接填成有效供给数量。",
        "https://static.cninfo.com.cn/finalpage/2026-05-15/1225308047.PDF", "accelink_issuer_20260514", "2026-05-14",
    ),
    _source(
        "ligent_hkex_20260305", "海信宽带（Ligent）港交所上市申请文件", "香港交易所 / Ligent", "S", "pass",
        "申请文件显示800G已经量产，1.6T截至申报时仍在客户样品验证并预计2026年下半年商业化；2025年全速率光模块设计产能2716.9万只、实际产量约2149万只。",
        "总产能混合PON、电信、400G和800G等产品，不能当成800G/1.6T产能；高端模块更复杂，相同设备时间对应的产量更低。",
        "https://www1.hkexnews.hk/app/sehk/2026/108264/documents/sehk26030502135.pdf", "ligent_hkex_application_20260305", "2026-03-05",
    ),
    _source(
        "hgg_ir_2026q1", "华工科技2025年年报与2026年第一季度业绩预告", "华工科技", "S", "pass_with_note",
        "2025年报把800G LPO列为研发试制，2026年第一季度预告则称400G、800G、1.6T发货量大幅增长。",
        "公司没有披露各速率数量、客户、良率和产能；可确认高速产品已经发货，但不能量化1.6T有效供给。",
        "https://static.cninfo.com.cn/finalpage/2026-04-14/1225097251.PDF", "hgg_issuer_2025annual_2026q1", "2026-04-14",
    ),
    _source(
        "broadcom_sian3_20250325", "Broadcom extends 200G/lane DSP and PHY leadership", "Broadcom", "S", "pass",
        "Broadcom disclosed the 3nm Sian3 200G/lane DSP for 800G and 1.6T, said 200G EML and photodiodes were in volume shipment, and planned Sian3 ramp in 2025Q3.",
        "The disclosure confirms a commercial component platform and millions of 200G EML shipments, but not unlimited DSP supply or allocation to any module vendor.",
        "https://investors.broadcom.com/news-releases/news-release-details/broadcom-extends-200glane-dsp-phy-leadership-next-generation-ai", "broadcom_200g_dsp_20250325", "2025-03-25",
        language="en", title_zh="Broadcom发布新一代200G每通道DSP与光器件", excerpt_zh="Broadcom披露3纳米Sian3 DSP面向800G与1.6T，并称200G EML和探测器已批量出货；这不等于器件无限供应或已分配给特定模块厂。",
    ),
    _source(
        "marvell_ara_1p6t", "Marvell Ara 1.6T PAM4 DSP product brief", "Marvell", "S", "pass",
        "Ara is a 3nm 1.6T PAM4 DSP with eight 200G electrical and eight 200G optical lanes for next-generation transceivers.",
        "A second commercial DSP platform reduces single-vendor dependence, but the product brief does not disclose total shipments, lead times or customer allocation.",
        "https://www.marvell.com/content/dam/marvell/en/public-collateral/dsp/marvell-ara-pam4-dsp-product-brief.pdf", "marvell_ara_1p6t_platform", "2025-01-01",
        language="en", title_zh="Marvell Ara 1.6T PAM4 DSP产品资料", excerpt_zh="Ara采用3纳米工艺，包含8路200G电口和8路200G光口；第二个平台降低单一供应商依赖，但没有公开总出货和分配。",
    ),
    _source(
        "lumentum_eml_capacity_20260625", "Why optical components will define the next era of data centers", "Lumentum", "S", "pass",
        "Lumentum calls EML capacity a near-term constraint and expects unit capacity at end-2026 to be more than 50% above end-2025; a new fab is not expected to ramp until mid-2028.",
        "The capacity increase is management guidance without absolute units and cannot be converted directly into 1.6T module supply.",
        "https://www.lumentum.com/en/blog/backbone-ai-infrastructure-why-optical-components-will-define-next-era-data-centers", "lumentum_component_capacity_20260625", "2026-06-25",
        language="en", title_zh="Lumentum讨论AI数据中心光器件产能", excerpt_zh="Lumentum把EML称为近期约束，并预计2026年末单位产能较2025年末增加50%以上；新工厂要到2028年中爬坡。",
    ),
    _source(
        "tower_sipho_capacity_2026", "Tower expands silicon-photonics capacity and signs customer contracts", "Tower Semiconductor", "S", "pass",
        "Tower targets December-2026 silicon-photonics wafer-start capacity above five times its Q4-2025 monthly shipments and disclosed $1.3 billion of 2027 customer contracts with prepayments.",
        "The base wafer count is undisclosed and contracts cannot be converted into module units; full starts and qualification extend into 2027.",
        "https://ir.towersemi.com/news-releases/news-release-details/tower-semiconductor-signs-customer-contracts-13-billion-silicon/", "tower_sipho_capacity_contracts_2026", "2026-05-13",
        language="en", title_zh="Tower扩充硅光产能并签署客户合同", excerpt_zh="Tower目标在2026年12月把硅光晶圆启动能力提高到2025年第四季度月出货的五倍以上，并披露2027年客户合同；基数未披露，不能换算模块数。",
    ),
    _source(
        "sumitomo_connector_capacity_202511", "Growth strategy for data-center-related business", "Sumitomo Electric", "S", "pass_with_note",
        "Sumitomo plans optical-connector product capacity in 2028 at roughly seven times the 2023 level and describes compact MMC ferrules for higher-density connectivity.",
        "This is a planned index for a mixed connector portfolio, not absolute MT/FA supply or a direct transceiver-capacity measure.",
        "https://sumitomoelectric.com/sites/default/files/2025-11/download_documents/Growth%20strategy%20for%20data%20center-related%20business_2025.pdf", "sumitomo_connector_capacity_202511", "2025-11-01",
        language="en", title_zh="住友电工数据中心业务增长战略", excerpt_zh="住友规划2028年光连接器产品产能约为2023年的七倍，并推进高密度MMC插芯；这是混合产品规划指数，不是光模块产能。",
    ),
    _source(
        "nvidia_b300_network_ra", "NVIDIA DGX SuperPOD B300 network fabrics reference architecture", "NVIDIA", "S", "pass",
        "The reference architecture connects each B300 GPU to two independent 400GbE compute-fabric planes; ConnectX-8 800G ports can break out into two 400G links.",
        "This is a configuration-specific endpoint count, not two 800G optical modules per GPU; twin-port optics, link ends and copper substitution must be modeled separately.",
        "https://docs.nvidia.com/dgx-superpod/reference-architecture/scalable-infrastructure-b300/latest/network-fabrics.html", "nvidia_b300_reference_architecture", "2026-01-01",
        language="en", title_zh="NVIDIA B300 SuperPOD网络参考架构", excerpt_zh="该参考架构为每颗B300 GPU配置两个独立400G计算网络端点；800G端口可拆成两路400G，不能直接换算为每GPU两只800G光模块。",
    ),
    _source(
        "meta_dsf_2025", "Disaggregated Scheduled Fabric: scaling Meta's AI journey", "Meta Engineering", "S", "pass",
        "Meta describes an 18,432-by-800G GPU fabric and edge pods with about 2,000 800G ports, while using 2x400G FR4 in specified fabric links.",
        "The topology is a useful deployment anchor but cannot be generalized to global module demand or treated as one identical optic per logical port.",
        "https://engineering.fb.com/2025/10/20/data-center-engineering/disaggregated-scheduled-fabric-scaling-metas-ai-journey/", "meta_dsf_topology_202510", "2025-10-20",
        language="en", title_zh="Meta分布式调度网络的AI集群拓扑", excerpt_zh="Meta披露18432个800G GPU连接和约2000个800G端口的边缘Pod，并在部分链路使用2×400G FR4；该拓扑不能直接外推全球需求。",
    ),
    _source(
        "nvidia_gb200_copper", "NVIDIA GB200 NVL72 networking design", "NVIDIA", "S", "pass",
        "The GB200 NVL72 scale-up domain uses more than 5,000 coaxial copper cables in four NVLink cable cartridges for 72 GPUs.",
        "The design is direct counter-evidence to multiplying every new GPU by a fixed pluggable-optics count; scale-up links can remain copper.",
        "https://developer.nvidia.com/blog/?p=90182", "nvidia_gb200_copper_scaleup", "2024-10-11",
        language="en", title_zh="NVIDIA GB200 NVL72采用大规模铜缆互连", excerpt_zh="GB200 NVL72的72颗GPU通过四个NVLink线缆盒和5000多根同轴铜缆完成扩展互连，反驳“GPU数量固定乘光模块数”的简化模型。",
    ),
    _source(
        "innolight_ar_2025", "中际旭创2025年年度报告", "中际旭创", "S", "pass",
        "2025年收入382.40亿元、归母净利润107.97亿元、经营现金流108.96亿元；光模块产能2806万只、产量2376万只、销量2109万只。",
        "光模块收入373.74亿元、毛利率42.61%；混合产能和销量跨产品代际，不能当成800G或1.6T单品数量。",
        "https://static.cninfo.com.cn/finalpage/2026-03-31/1225056458.PDF", "innolight_issuer_2025ar", "2026-03-31",
    ),
    _source(
        "innolight_q1_2026", "中际旭创2026年第一季度报告", "中际旭创", "S", "pass",
        "第一季度收入194.96亿元、归母净利润57.35亿元、经营现金流33.68亿元，倒算毛利率约46.1%。",
        "在建工程、预付款、应收款和购建长期资产现金支出大增，说明利润、现金流和有效产能不能按一个比例外推。",
        "https://static.cninfo.com.cn/finalpage/2026-04-17/1225111941.PDF", "innolight_issuer_2026q1", "2026-04-17",
    ),
    _source(
        "innolight_ir_20260424", "中际旭创2025年度业绩说明会记录", "中际旭创", "S", "pass",
        "公司称1.6T已量产并将逐季增加，已收到部分客户2026全年订单，年末总年化产能约2800万只且2026继续扩产。",
        "公司同时称部分光电芯片、PCB和无源器件偏紧；混合年化产能必须乘产品结构、良率、利用率和客户分配。",
        "https://static.cninfo.com.cn/finalpage/2026-04-24/1225185699.PDF", "innolight_ir_20260424", "2026-04-24",
    ),
    _source(
        "eoptolink_ar_2025", "新易盛2025年年度报告", "新易盛", "S", "pass",
        "2025年收入248.42亿元、归母净利润95.32亿元、经营现金流77.01亿元、现金资本开支13.20亿元。",
        "光互联产能1747万只、产量1634万只、销量1603万只，光产品收入247.71亿元、毛利率47.81%，海外收入占比约96%。",
        "https://disc.static.szse.cn/disc/disk03/finalpage/2026-04-24/e20c68b8-9ce5-4751-acfd-9fb5f4e44645.PDF", "eoptolink_issuer_2025ar", "2026-04-24",
    ),
    _source(
        "eoptolink_q1_2026", "新易盛2026年第一季度报告", "新易盛", "S", "pass",
        "第一季度收入83.38亿元、归母净利润27.80亿元、经营现金流6.84亿元，倒算毛利率约49.2%。",
        "预付款、在建工程和购建长期资产现金支出显著增加，经营现金流仅约为归母利润四分之一。",
        "https://static.cninfo.com.cn/finalpage/2026-04-24/1225172606.PDF", "eoptolink_issuer_2026q1", "2026-04-24",
    ),
    _source(
        "eoptolink_xpo_2026", "Eoptolink unveils 12.8T liquid-cooled pluggable optics", "Eoptolink", "S", "pass_with_note",
        "Eoptolink joined the XPO MSA and unveiled a 12.8T liquid-cooled pluggable design alongside 400G-per-lane and multiple 1.6T architectures.",
        "This shows an active response to architecture change, while a product launch still requires customer qualification and revenue conversion.",
        "https://www.eoptolink.com/news/13-new-products/364-eoptolink-joins-xpo-msa-and-unveils-industry-first-12-8-tbps-liquid-cooled-pluggable-optics-for-ai-data-centers", "eoptolink_xpo_202603", "2026-03-12",
        language="en", title_zh="新易盛发布12.8T液冷可插拔光学方案", excerpt_zh="新易盛加入XPO MSA并发布12.8T液冷可插拔及多种1.6T路线，显示应对架构变化；发布仍需客户和收入验证。",
    ),
    _source(
        "sourcephotonics_asp_mix", "Source Photonics listing application", "Hong Kong Stock Exchange / Source Photonics", "S", "pass",
        "The filing reports data-center module volume of 1.158 million units in 2023, 1.609 million in 2024 and 2.411 million in the first nine months of 2025, with blended ASP rising as high-speed mix increased.",
        "The disclosure shows blended ASP equals product-mix effect plus same-generation price change and must not be mislabeled as 800G or 1.6T ASP.",
        "https://www1.hkexnews.hk/app/sehk/2026/108550/documents/sehk26051901436.pdf", "sourcephotonics_listing_2026", "2026-05-19",
        language="en", title_zh="索尔思光电港交所申请文件", excerpt_zh="文件披露数据中心模块销量和混合ASP，并明确高端产品占比推动混合ASP上升；混合ASP不能当作同代产品涨价。",
    ),
    _source(
        "innolight_market_snapshot_202607", "中际旭创Wind财务、估值与一致预期快照", "Wind", "A", "pass",
        "截至2026年7月22日，总市值11830.41亿元、PE TTM 79.14倍、PB 34.16倍、ROE TTM 42.01%、ROA TTM 33.44%；FY1—FY3一致预期归母净利润为303.84/534.87/794.13亿元。",
        "未来PB和ROA没有可用的供应商直接预测；报告只在冻结外部快照后，以一致预期ROE和留存收益桥作诊断，不把内部计算伪装成Wind字段。",
        "cache/research_runs/opportunity_lens_run13_byd_luxshare_20260722/financial_snapshot_v4.json", "wind_structured_snapshot_20260722_300308", "2026-07-22",
        role="external_benchmark", content_sha256="273c9e5981368d43323ccd39762809876902c6317452c0ecb89faa5bdc9b8c8f",
    ),
    _source(
        "eoptolink_market_snapshot_202607", "新易盛Wind财务、估值与一致预期快照", "Wind", "A", "pass",
        "截至2026年7月22日，总市值7093.98亿元、PE TTM 66.05倍、PB 36.54倍、ROE TTM 52.70%、ROA TTM 41.21%；FY1—FY3一致预期归母净利润为190.17/304.93/484.14亿元。",
        "未来PB和ROA没有可用的供应商直接预测；报告只在冻结外部快照后，以一致预期ROE和留存收益桥作诊断。",
        "cache/research_runs/opportunity_lens_run13_byd_luxshare_20260722/financial_snapshot_v4.json", "wind_structured_snapshot_20260722_300502", "2026-07-22",
        role="external_benchmark", content_sha256="273c9e5981368d43323ccd39762809876902c6317452c0ecb89faa5bdc9b8c8f",
    ),
    _source(
        "luxshare_market_snapshot_202607", "立讯精密Wind财务、估值与一致预期快照", "Wind", "A", "pass",
        "截至2026年7月22日，总市值4570.27亿元、PE TTM 26.55倍、PB 4.16倍、ROE TTM 19.37%、ROA TTM 6.35%；FY1—FY3一致预期归母净利润为216.55/278.43/344.65亿元。",
        "光模块分部没有独立盈利预测；集团一致预期只能用作总盘子对账，不能证明光模块客户、出货或利润率。",
        "cache/research_runs/opportunity_lens_run13_byd_luxshare_20260722/financial_snapshot_v4.json", "wind_structured_snapshot_20260722_002475", "2026-07-22",
        role="external_benchmark", content_sha256="273c9e5981368d43323ccd39762809876902c6317452c0ecb89faa5bdc9b8c8f",
    ),
    _source(
        "byd_market_snapshot_202607", "比亚迪Wind财务、估值与一致预期快照", "Wind", "A", "pass",
        "截至2026年7月22日，总市值8348.62亿元、PE TTM 30.31倍、PB 3.60倍、ROE TTM 11.02%、ROA TTM 3.71%；FY1—FY3一致预期归母净利润为409.68/515.70/622.76亿元。",
        "潜在光模块业务更可能由非全资子公司承载，项目收入、项目利润和比亚迪股份归母增量必须分开，不能把子公司利润100%归母。",
        "cache/research_runs/opportunity_lens_run13_byd_luxshare_20260722/financial_snapshot_v4.json", "wind_structured_snapshot_20260722_002594", "2026-07-22",
        role="external_benchmark", content_sha256="273c9e5981368d43323ccd39762809876902c6317452c0ecb89faa5bdc9b8c8f",
    ),
    _source(
        "innolight_pb_history_202607", "中际旭创月度PB与年度资本回报序列", "Wind", "A", "pass",
        "2021年1月至2026年7月共取得67个月末PB观测，中位数为6.08倍、20%—80%分位为2.73—10.59倍；2026年7月22日PB为34.16倍，位于样本约96.3%分位。",
        "历史PB分位只说明当前估值在这段样本中的位置，不是目标PB；年度ROE与PB对照使用财报披露日后的市场值，避免把年末尚未公开的财务数据提前用于估值。",
        "opportunity_lens/research_outputs/20260722_byd_luxshare_optical_competition_run13/pb_return_history_v1.json", "wind_pb_return_history_300308_20260722", "2026-07-22",
        role="external_benchmark", content_sha256="1a858b9d03eab88bec8786e9872845b21ab5d6fd933342c0889c6b11dabb3cef",
    ),
    _source(
        "eoptolink_pb_history_202607", "新易盛月度PB与年度资本回报序列", "Wind", "A", "pass",
        "2021年1月至2026年7月共取得67个月末PB观测，中位数为8.19倍、20%—80%分位为4.06—14.43倍；2026年7月22日PB为36.54倍，位于样本约97.8%分位。",
        "高分位不能单独证明高估，也不能把历史中位数直接当目标PB；必须同时判断高速产品增长、ROE、ROA和现金转换能否持续。",
        "opportunity_lens/research_outputs/20260722_byd_luxshare_optical_competition_run13/pb_return_history_v1.json", "wind_pb_return_history_300502_20260722", "2026-07-22",
        role="external_benchmark", content_sha256="1a858b9d03eab88bec8786e9872845b21ab5d6fd933342c0889c6b11dabb3cef",
    ),
    _source(
        "luxshare_pb_history_202607", "立讯精密月度PB与年度资本回报序列", "Wind", "A", "pass",
        "2021年1月至2026年7月共取得67个月末PB观测，中位数为5.11倍、20%—80%分位为4.36—7.66倍；2026年7月22日PB为4.16倍，位于样本约17.2%分位。",
        "当前PB处于历史偏低位置只提供估值参照；消费电子周期、新业务爬坡、经营性占款与有息负债、现金流质量仍会改变可比性。",
        "opportunity_lens/research_outputs/20260722_byd_luxshare_optical_competition_run13/pb_return_history_v1.json", "wind_pb_return_history_002475_20260722", "2026-07-22",
        role="external_benchmark", content_sha256="1a858b9d03eab88bec8786e9872845b21ab5d6fd933342c0889c6b11dabb3cef",
    ),
    _source(
        "byd_pb_history_202607", "比亚迪月度PB与年度资本回报序列", "Wind", "A", "pass",
        "2021年1月至2026年7月共取得67个月末PB观测，中位数为6.26倍、20%—80%分位为4.44—8.65倍；2026年7月22日PB为3.60倍，位于样本约2.2%分位。",
        "当前PB处于样本低位不等于必然低估；汽车价格竞争、资产周转、资本开支、现金流和集团多业务结构必须共同验证。",
        "opportunity_lens/research_outputs/20260722_byd_luxshare_optical_competition_run13/pb_return_history_v1.json", "wind_pb_return_history_002594_20260722", "2026-07-22",
        role="external_benchmark", content_sha256="1a858b9d03eab88bec8786e9872845b21ab5d6fd933342c0889c6b11dabb3cef",
    ),

    # 本地研报渠道：只用于外部观点和差异对账，不替代一手证据
    _source(
        "report_hsbc_luxshare_202605", "Luxshare: underappreciated optical-interconnect beneficiary", "HSBC Global Investment Research", "B", "pass_with_note",
        "The report expects optical modules to become a growth driver and provides explicit revenue assumptions for Luxshare.",
        "Its customer, shipment and margin assumptions are analyst estimates and are kept outside the independent model until reconciliation.",
        "papers/比亚迪 立讯精密 光模块/2026-05-15_hsbc global investment research_立讯精密_立讯精密（002475）：买入：被低估的光互连需求受益标的.pdf", "report_hsbc_luxshare_202605", "2026-05-15",
        channel="report", language="en", title_zh="立讯精密：被低估的光互连需求受益标的", excerpt_zh="报告把光模块视为立讯增长驱动并给出收入假设；客户、出货和利润率属于分析师预测，只用于外部对账。",
    ),
    _source(
        "report_jpm_luxshare_202606", "Luxshare: optical-module ramp may drive growth", "J.P. Morgan", "B", "pass_with_note",
        "The report forecasts optical-module ramp from the second half of 2026 and a 10%/16% earnings contribution in 2027/2028.",
        "These are sell-side estimates, not audited segment results or named-customer qualification evidence.",
        "papers/比亚迪 立讯精密 光模块/2026-06-26_jpmorgan_立讯精密_立讯精密（002475）：立讯精密；超出预期的iphone需求及光模块潜在放量将推动增长：回调时买入.pdf", "report_jpm_luxshare_202606", "2026-06-26",
        channel="report", language="en", title_zh="立讯光模块潜在放量可能推动增长", excerpt_zh="报告预测立讯光模块从2026年下半年放量并在2027/2028年贡献10%/16%利润；这是卖方估计而非审计结果。",
    ),
    _source(
        "report_cicc_optics_202605", "从消费电子到光通信，光学厂商迎来新机遇", "中金公司", "B", "pass_with_note",
        "报告比较消费电子与光通信制造能力的可迁移环节，并讨论硅光、封装与自动化。",
        "行业类比可用于提出迁移路径，但不能替代单一公司的产品、客户、良率和收入证据。",
        "papers/比亚迪 立讯精密 光模块/2026-05-24_中金公司_电子_从消费电子到光通信，光学厂商迎来新机遇.pdf", "report_cicc_optics_202605", "2026-05-24", channel="report",
    ),
    _source(
        "report_ms_ai_hardware_202607", "大中华科技硬件：计算的基石", "Morgan Stanley", "B", "pass_with_note",
        "报告覆盖服务器、AI基础设施、电子元器件和主要硬件制造商的产业链位置。",
        "宏观产业链判断只作为候选和外部观点，不用于替代公司官方光模块进度。",
        "papers/比亚迪 立讯精密 光模块/2026-07-15_morgan stanley_电子_大中华科技硬件：计算的基石：服务器、人工智能基础设施与电子元器件.pdf", "report_ms_ai_hardware_202607", "2026-07-15", channel="report",
    ),
    _source(
        "report_zhiyan_optics_202607", "中国光模块行业发展现状及未来趋势研判报告", "智研咨询", "B", "pass_with_note",
        "报告汇总国内光模块企业、产能、财务和竞争格局，并给出二手市场份额数据。",
        "汇总表中的市场份额和客户归属必须回到原始机构或公司资料后才能进入核心判断。",
        "papers/比亚迪 立讯精密 光模块/2026-07-16_智研咨询_电子_中国光模块行业发展现状及未来趋势研判报告.pdf", "report_zhiyan_optics_202607", "2026-07-16", channel="report",
    ),
]


def build_data_points() -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for index, source in enumerate(SOURCES, start=1):
        ref = str(source["ref"])
        title = str(source.get("title_zh") or source["title"])
        period = str(source.get("published_at") or "2026-07-22")
        excerpt = str(source.get("excerpt_zh") or source["excerpt"])
        if str(source.get("language") or "").startswith("en"):
            fact2 = str(
                source.get("fact2_zh")
                or "该来源只支持上述公开范围，不能自动外推为具名客户资格、稳定批量、可持续良率、市场份额或盈利结果。"
            )
        else:
            fact2 = str(source["fact2"])
        for suffix, metric, value_text, scope in (
            ("core", f"{title}的核心事实", excerpt, "core_fact"),
            ("boundary", f"{title}的适用边界", fact2, "evidence_boundary"),
        ):
            point = {
                "data_point_key": f"run13.{ref}.{suffix}",
                "metric": metric,
                "value_text": value_text,
                "unit": "事实",
                "period": period,
                "scope_key": scope,
                "source_ref": ref,
                "source_excerpt": str(source["excerpt"]),
            }
            if str(source.get("language") or "").startswith("en"):
                point["source_excerpt_zh"] = excerpt
            points.append(point)
    return points


def build_claims() -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for index, source in enumerate(SOURCES, start=1):
        claim = {
            "claim_id": f"run13.claim.{index:03d}",
            "claim_type": "来源事实与边界",
            "claim_text": str(source.get("excerpt_zh") or source["excerpt"]),
            "source_ref": str(source["ref"]),
            "source_excerpt": str(source["excerpt"]),
            "confidence": "高" if source["source_tier"] in {"S", "A"} and source["source_review_status"] == "pass" else "中",
        }
        if str(source.get("language") or "").startswith("en"):
            claim["source_excerpt_zh"] = str(source["excerpt_zh"])
        claims.append(claim)
    return claims
