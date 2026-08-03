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
    review_status: str = "pass",
    language: str = "zh",
    title_zh: str | None = None,
    excerpt_zh: str | None = None,
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
            f"归入“{independence_key}”；同一公告、报告、转载或共同底稿只计一个独立证据组。"
        ),
        "source_channel": channel,
    }
    if url:
        row["url"] = url
    if local_path:
        row["local_path"] = local_path
    if date:
        row["published_at"] = date
    if language != "zh":
        row["title_zh"] = title_zh or title
        row["excerpt_zh"] = excerpt_zh or excerpt
    return row


SOURCES: list[dict[str, Any]] = [
    _source(
        "r-chint-ar2025",
        "正泰电器2025年年度报告",
        "浙江正泰电器股份有限公司",
        channel="report",
        tier="S",
        independence_key="chint_2025_annual_report",
        local_path="papers/正泰电器/公司财报/正泰电器_2025年年度报告_20260416.pdf",
        date="2026-04-16",
        excerpt="披露2025年合并财务、分业务销售模式、正泰安能经营、担保、项目资产和现金流明细。",
    ),
    _source(
        "r-chint-q12026",
        "正泰电器2026年第一季度报告",
        "浙江正泰电器股份有限公司",
        channel="report",
        tier="S",
        independence_key="chint_2026_q1_report",
        local_path="papers/正泰电器/公司财报/正泰电器_2026年第一季度报告_20260416.pdf",
        date="2026-04-16",
        excerpt="2026年一季度收入213.03亿元、归母净利润12.67亿元、经营现金流41.19亿元。",
    ),
    _source(
        "r-chint-ar2024",
        "正泰电器2024年年度报告",
        "浙江正泰电器股份有限公司",
        channel="report",
        tier="S",
        independence_key="chint_2024_annual_report",
        local_path="papers/正泰电器/公司财报/正泰电器_2024年年度报告_20250430.pdf",
        date="2025-04-30",
        excerpt="披露2024年合并财务、光伏电站转让、开发运营和EPC分业务收入与毛利率。",
    ),
    _source(
        "r-chint-ar2023",
        "正泰电器2023年年度报告",
        "浙江正泰电器股份有限公司",
        channel="report",
        tier="S",
        independence_key="chint_2023_annual_report",
        local_path="papers/正泰电器/公司财报/正泰电器_2023年年度报告_20240430.pdf",
        date="2024-04-30",
        excerpt="披露2023年合并财务以及户用光伏开发运营、转让、EPC业务的经营基数。",
    ),
    _source(
        "r-aneng-ipo2025",
        "正泰安能首次公开发行招股说明书申报稿",
        "正泰安能数字能源（浙江）股份有限公司",
        channel="report",
        tier="S",
        independence_key="aneng_ipo_prospectus_20250630",
        local_path="papers/正泰电器/业务模式与监管问询/正泰安能_招股说明书申报稿_20250630.pdf",
        url="https://static.sse.com.cn/stock/disclosure/announcement/c/202506/001990_20250630_KSIS.pdf",
        date="2025-06-30",
        excerpt="系统披露2022—2024年合作运营、电站销售、运维、客户、毛利、现金流、资产负债和长期义务。",
    ),
    _source(
        "r-aneng-inquiry1",
        "正泰安能首轮审核问询回复",
        "正泰安能数字能源（浙江）股份有限公司",
        channel="report",
        tier="S",
        independence_key="aneng_ipo_inquiry_round1_20240116",
        local_path="papers/正泰电器/业务模式与监管问询/正泰安能_首轮审核问询回复_20240116.pdf",
        url="https://static.sse.com.cn/stock/disclosure/announcement/c/202401/001990_20240116_L6UJ.pdf",
        date="2024-01-16",
        excerpt="解释业务之间的转换、资金流、运维责任、发电量保障、拆站及光伏贷款风险。",
    ),
    _source(
        "r-aneng-inquiry2",
        "正泰安能第二轮审核问询回复",
        "正泰安能数字能源（浙江）股份有限公司",
        channel="report",
        tier="S",
        independence_key="aneng_ipo_inquiry_round2_20240629",
        local_path="papers/正泰电器/业务模式与监管问询/正泰安能_第二轮审核问询回复_20240629.pdf",
        url="https://static.sse.com.cn/stock/disclosure/announcement/c/202406/001990_20240629_2Z1V.pdf",
        date="2024-06-29",
        excerpt="说明光伏贷、融资租赁、代理商反担保、项目收益偿还贷款和公司尾部责任。",
    ),
    _source(
        "r-chint-esg2025",
        "正泰电器2025年度可持续发展报告",
        "浙江正泰电器股份有限公司",
        channel="report",
        tier="A",
        independence_key="chint_2025_sustainability_report",
        local_path="papers/正泰电器/业务模式与监管问询/正泰电器_2025年度可持续发展报告_20260416.pdf",
        date="2026-04-16",
        excerpt="披露供应商、客户服务、质量、乡村光伏和环境社会治理措施，属于公司自述。",
    ),
    _source(
        "r-glms-20260416",
        "正泰电器2025年年报及2026年一季报点评",
        "国联民生证券",
        channel="report",
        tier="B",
        independence_key="glms_chint_model_20260416",
        local_path="papers/正泰电器/2026-04-16_国联民生证券_正泰电器_正泰电器（601877）：25年年报及26年一季报点评：低压电器稳步增长，轻资产业务为新能源重要增量.pdf",
        date="2026-04-16",
        excerpt="预测2026—2028年收入632.46、676.66、729.63亿元，归母净利润57.66、70.75、85.29亿元。",
    ),
    _source(
        "r-ebscn-20260421",
        "正泰电器2025年年报与2026年一季报点评",
        "光大证券",
        channel="report",
        tier="B",
        independence_key="ebscn_chint_model_20260421",
        local_path="papers/正泰电器/2026-04-21_光大证券_正泰电器_正泰电器（601877）：2025年年报&2026年一季报点评：户用光伏业务维持高质量发展，数据中心领域持续突破.pdf",
        date="2026-04-21",
        excerpt="预测2026—2028年收入588.86、610.87、635.34亿元，归母净利润51.42、58.10、66.26亿元。",
    ),
    _source(
        "r-cicc-20260528",
        "现金流不稳下的平衡术：分布式光伏机构间REITs条款解析",
        "中金公司",
        channel="report",
        tier="B",
        independence_key="cicc_distributed_pv_reits_20260528",
        local_path="papers/正泰电器/2026-05-28_中金公司_宏观研究_现金流不稳下的平衡术：分布式光伏机构间reits条款解析.pdf",
        date="2026-05-28",
        excerpt="分析分布式光伏资产在机构间转让、收益权安排和现金流波动下的合同与估值问题。",
    ),
    _source(
        "r-cjsc-20260507",
        "正泰电器：低压盈利韧性凸显，新兴下游有望贡献增量",
        "长江证券",
        channel="report",
        tier="B",
        independence_key="cjsc_chint_model_20260507",
        local_path="papers/正泰电器/2026-05-07_长江证券_正泰电器_正泰电器（601877）：低压盈利韧性凸显，新兴下游有望贡献增量.pdf",
        date="2026-05-07",
        excerpt="预测2026—2028年收入758.71、872.51、1003.39亿元，但2026年经营现金流为负80.72亿元。",
    ),
    _source(
        "r-ms-20260518",
        "正泰电器：停止覆盖时的最终财务模型",
        "摩根士丹利",
        channel="report",
        tier="B",
        independence_key="morgan_stanley_chint_final_model_20260518",
        local_path="papers/正泰电器/2026-05-18_morgan stanley_正泰电器_正泰电器（601877）：停止覆盖.pdf",
        date="2026-05-18",
        excerpt=(
            "停止覆盖时更新2026—2028年收入、归母净利润和现金流预测，"
            "并以7.9% WACC、零终端增长的DCF给出33.27元目标价；"
            "该模型只用于截至报告日的对账，不视为持续更新的活跃覆盖。"
        ),
    ),
    _source(
        "r-xyzq-20260427",
        "正泰电器：业绩稳步上升，海外业务有望成为新增长点",
        "兴业证券",
        channel="report",
        tier="B",
        independence_key="xyzq_chint_model_20260427",
        local_path="papers/正泰电器/2026-04-27_兴业证券_正泰电器_正泰电器（601877）：业绩稳步上升，海外业务有望成为新增长点.pdf",
        date="2026-04-27",
        excerpt="预测2026—2028年收入628.91、679.43、740.75亿元，归母净利润52.55、62.01、73.04亿元。",
    ),
    _source(
        "r-rmi-20251221",
        "中国分布式光伏韧性发展路径：2026与2027年展望",
        "落基山研究所",
        channel="report",
        tier="A",
        independence_key="rmi_distributed_pv_outlook_20251221",
        local_path="papers/正泰电器/2025-12-21_rmi_电力设备_中国分布式光伏韧性发展路径：2026与2027年展望报告.pdf",
        date="2025-12-21",
        excerpt="讨论分布式光伏消纳、电价市场化、商业模式和项目韧性，并非公司特定事实。",
    ),
    _source(
        "w-nea-measures",
        "分布式光伏发电开发建设管理办法及政策解读",
        "国家能源局",
        channel="web",
        tier="S",
        independence_key="nea_distributed_pv_measures_2025",
        url="https://www.nea.gov.cn/20250123/fc3505a164484316b9720b5298e92a0b/c.html",
        date="2025-01-23",
        excerpt="非自然人投资项目不得以自然人名义备案，新老项目按备案和投产时间衔接。",
    ),
    _source(
        "w-ndrc-136",
        "关于深化新能源上网电价市场化改革促进新能源高质量发展的通知",
        "国家发展改革委、国家能源局",
        channel="web",
        tier="S",
        independence_key="ndrc_nea_2025_136",
        url="https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=20482",
        date="2025-01-27",
        excerpt="新能源上网电量全面进入电力市场，存量和增量项目采用不同的价格结算机制。",
    ),
    _source(
        "w-nea-standard-contract",
        "非自然人户用分布式光伏项目场所租赁标准合同范本",
        "国家能源局、中国光伏行业协会",
        channel="web",
        tier="A",
        independence_key="nea_cpai_standard_lease_2025",
        url="https://www.nea.gov.cn/20251219/e7e3bbcaf9b248e0a48a298b135b75e1/c.html",
        local_path="papers/正泰电器/合同与司法案例/非自然人户用分布式光伏项目场所租赁标准合同范本_20251219.docx",
        date="2025-12-19",
        excerpt="标准范本明确场地、资产、建设、运维、漏水责任、收益和退出安排。",
    ),
    _source(
        "w-cpia-household-contract-template",
        "户用光伏电站合作开发合同范本",
        "中国光伏行业协会、泉州市发展和改革委员会",
        channel="web",
        tier="A",
        independence_key="cpia_household_pv_contract_template_2022",
        url="https://fgw.quanzhou.gov.cn/jlhd/bgxz/202304/t20230413_2869019.htm",
        local_path="papers/正泰电器/合同与司法案例/户用光伏电站合作开发合同范本_中国光伏行业协会_20220830.pdf",
        date="2022-08-30",
        excerpt=(
            "范本逐条约定电费结算账户和收益划转、设备所有权、农户屋顶权属与保管义务、"
            "运营方施工运维和漏水责任、拆迁处置及双方违约责任。"
        ),
    ),
    _source(
        "w-weifang-court-electronic-contract",
        "电子合同（电子签名）的法律效力认定浅析",
        "潍坊市中级人民法院",
        channel="web",
        tier="S",
        independence_key="weifang_court_household_pv_econtract_case_2026",
        url="https://www.sdcourt.gov.cn/wfzy/442541/442474/44608845/index.html",
        date="2026-05-28",
        excerpt=(
            "真实案件中，农户与光伏公司补签屋顶租赁电子合同，约定无故毁约或阻挠施工"
            "违约金2万元；法院确认合同有效，并就擅自拆除判令返还支架、支付1万元违约金。"
        ),
    ),
    _source(
        "w-yuzhou-court-roof-leak",
        "户用光伏发电设备安装后屋顶漏水",
        "禹州市人民法院",
        channel="web",
        tier="S",
        independence_key="wuchuan_court_household_pv_roof_leak_case_2025",
        url="https://yzsfy.hncourt.gov.cn/public/detail.php?id=9139",
        date="2025-10-15",
        excerpt=(
            "20年屋顶租赁项目发生漏水和农户剪线，企业主张租金、项目造价和违约金近50万元；"
            "调解结果要求企业先修复防水并承担后续质保，农户随后恢复通电。"
        ),
    ),
    _source(
        "w-baiyin-court-pv-loan",
        "白银中院2022年度典型案件：光伏贷合同纠纷",
        "白银市中级人民法院",
        channel="web",
        tier="S",
        independence_key="baiyin_court_household_pv_loan_case_2022",
        url="https://www.chinagscourt.gov.cn/Wap/Show/79477",
        date="2023-02-08",
        excerpt=(
            "近百户农户以本人名义办理5—6年光伏贷款，发电收益约370元/月且不足以偿付利息；"
            "法院协调补贴和电价后，合同继续履行，表明借款人身份会决定经营偏差由谁承担。"
        ),
    ),
    _source(
        "w-jiangyin-warning",
        "预防屋顶分布式光伏发电项目建设风险告知书",
        "江阴市人民政府",
        channel="web",
        tier="A",
        independence_key="jiangyin_rooftop_pv_warning_2025",
        url="https://www.jiangyin.gov.cn/doc/2025/07/29/1344137.shtml",
        date="2025-07-29",
        excerpt="提示农户警惕以个人名义融资、收益权质押、维护责任和资产转让条款。",
    ),
    _source(
        "w-ningguo-guidance",
        "农村安装光伏的风险答复",
        "宁国市人民政府",
        channel="web",
        tier="A",
        independence_key="ningguo_rooftop_pv_guidance_2025",
        url="https://www.ningguo.gov.cn/InFeedback/show/139006.html",
        date="2025-08-24",
        excerpt="地方政府提示代理商资质、收益夸大、合同细节和长期屋顶租赁风险。",
    ),
    _source(
        "w-aneng-rural-model",
        "农村家庭户用光伏解决方案",
        "正泰安能数字能源（浙江）股份有限公司",
        channel="web",
        tier="A",
        independence_key="aneng_official_rural_model",
        url="https://chintanneng.com/solution/detail/id/10000.html",
        excerpt="公司公开模式为企业投资运维、农户提供闲置屋顶并获得电站收益分享。",
    ),
    _source(
        "w-aneng-complaint-response",
        "屋顶光伏漏水与裂缝报道及正泰安能回应",
        "华夏时报（新浪财经转载）",
        channel="web",
        tier="C",
        independence_key="aneng_roof_complaint_report_20260315",
        url="https://finance.sina.cn/2026-03-15/detail-inhqzqry3606339.d.html",
        date="2026-03-15",
        excerpt=(
            "报道展示一份区域合作方与农户签署的“金顶宝”屋顶租赁合同：75kW、120块组件、"
            "15元/块·年、年租金1800元；正泰安能称租金已进入专用账户并完成漏水维修。"
            "该材料能说明个案条款和结算接口，但不能代表全部正泰项目。"
        ),
    ),
    _source(
        "w-zoucheng-court-rooftop-contract",
        "（2023）鲁0883民初6828号房屋租赁合同纠纷民事判决书",
        "山东省邹城市人民法院（裁判文书网原稿，Wikisource镜像）",
        channel="web",
        tier="A",
        independence_key="zoucheng_rooftop_pv_contract_judgment_2023",
        url=(
            "https://zh.wikisource.org/wiki/"
            "%C3%97%C3%97%E5%85%AC%E5%8F%B8%E3%80%81%E5%AD%9F%E6%9F%90%E6%9F%90"
            "%E6%88%BF%E5%B1%8B%E7%A7%9F%E8%B5%81%E5%90%88%E5%90%8C%E7%BA%A0%E7%BA%B7"
            "%E6%B0%91%E4%BA%8B%E4%B8%80%E5%AE%A1%E6%B0%91%E4%BA%8B%E5%88%A4%E5%86%B3"
            "%E4%B9%A6"
        ),
        local_path=(
            "papers/正泰电器/合同与司法案例/"
            "邹城法院_屋顶光伏租赁合同纠纷判决书_20231024.html"
        ),
        date="2023-10-24",
        excerpt=(
            "判决书逐条载明真实《屋顶光伏租赁合同》及补充协议：企业全额投资、农户零投资；"
            "62块组件按35元/块·年支付2170元租金；发电收益归企业，先进入农户名下结算卡后按月"
            "划给企业。判决同时披露2022年8月至2023年6月逐月电费合计12455.21元，并将合同约定"
            "的日千分之五违约金调低为一年期LPR。"
        ),
    ),
    _source(
        "w-astronergy-n7-datasheet",
        "ASTRO N7 2.0 625—650W组件规格书",
        "正泰新能科技股份有限公司",
        channel="web",
        tier="A",
        independence_key="astronergy_n7_625_650w_datasheet_2025",
        url=(
            "https://www.astronergy.com/wp-content/uploads/2025/08/"
            "625650ASTRO-N7-2.0_CHSM66RNDGF-BH_ZBB_2382x1134x30_EN_20250819.pdf"
        ),
        date="2025-08-19",
        language="en",
        title_zh="正泰新能ASTRO N7 2.0 625—650W组件规格书",
        excerpt=(
            "正泰新能官方规格书给出625—650W功率范围和2382×1134×30毫米外形尺寸；"
            "本研究仅据此估算100平方米平屋顶的组件物理占地，不把可安装数量当作施工承诺。"
        ),
        excerpt_zh=(
            "正泰新能官方规格书给出625—650W功率范围和2382×1134×30毫米外形尺寸；"
            "本研究仅据此估算100平方米平屋顶的组件物理占地，不把可安装数量当作施工承诺。"
        ),
    ),
    _source(
        "w-aneng-stake",
        "正泰电器11.16亿元竞得正泰安能3.16%股权",
        "经济观察网",
        channel="web",
        tier="B",
        independence_key="chint_aneng_stake_transaction_20260710",
        url="https://jg-static.eeo.com.cn/article/info?id=a1776343d56a42c5951544a1ccd4aa2c",
        date="2026-07-10",
        excerpt="交易对价11.16亿元，对应3.16%股权，交易后正泰电器持股比例升至71.24%。",
    ),
    _source(
        "r-run15-model",
        "Run15正泰电器独立财务与估值模型",
        "本研究",
        channel="report",
        tier="B",
        independence_key="run15_chint_independent_model",
        local_path="opportunity_lens/research_outputs/20260725_chint_pv_profit_quality_run15/financial_artifacts/run15_chint_financial_model.json",
        date="2026-07-25",
        excerpt="按业务拆分收入与毛利，重建归母净利润、经营现金流、自由现金流、分部估值和PB—ROE交叉验证。",
    ),
    _source(
        "r-run15-household-contract-model",
        "Run15典型农户户用光伏合同四方现金流模型",
        "本研究",
        channel="report",
        tier="B",
        independence_key="run15_household_contract_cashflow_model",
        local_path="opportunity_lens/research_outputs/20260725_chint_pv_profit_quality_run15/financial_artifacts/run15_household_contract_cashflow_model.json",
        date="2026-07-27",
        excerpt=(
            "以正泰安能2024年合作运营规模和经营数据构造27.19kW统计代表站，"
            "分拆农户租金、运维、资产转让、融资偿还和不利情景；所有融资与维修假设均单独标注。"
        ),
    ),
    _source(
        "r-run15-household-group-bridge",
        "Run15单户合同到正泰电器集团现金流与估值传导模型",
        "本研究",
        channel="report",
        tier="B",
        independence_key="run15_household_group_valuation_bridge",
        local_path="opportunity_lens/research_outputs/20260725_chint_pv_profit_quality_run15/financial_artifacts/run15_household_to_group_valuation_bridge.json",
        date="2026-07-27",
        excerpt=(
            "先用100平方米案例识别现金与责任归属，再以公司披露的27GW以上保障义务、"
            "每瓦运维费、实际补偿率和预计负债校准组合风险，最后传导到集团利润、"
            "现金流、每股价值和条件化买卖区间。"
        ),
    ),
    _source(
        "r-run15-reconciliation",
        "Run15正泰电器独立模型与外部预测对账",
        "本研究",
        channel="report",
        tier="B",
        independence_key="run15_chint_external_reconciliation",
        local_path="opportunity_lens/research_outputs/20260725_chint_pv_profit_quality_run15/financial_artifacts/run15_external_reconciliation.json",
        date="2026-07-25",
        excerpt=(
            "独立模型先冻结，再与最近两个季度的五家机构报告及Wind"
            "一致预期逐年对比收入、归母净利润与经营现金流差异。"
        ),
    ),
]


def _fact(
    source_ref: str,
    entity_key: str,
    metric: str,
    value: Any,
    unit: str,
    period: str,
    scope_key: str,
    note: str,
    *,
    extraction_method: str = "pdf_direct",
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
    }


def build_fact_specs() -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []

    consolidated = {
        "2023": ("r-chint-ar2023", 572.51, 36.86, 41.40, 43.64, 9.77, 21.97),
        "2024": ("r-chint-ar2024", 645.19, 38.74, 152.02, 29.51, 9.54, 23.50),
        "2025": ("r-chint-ar2025", 591.45, 45.01, 230.90, 18.85, 10.39, 26.00),
    }
    for year, row in consolidated.items():
        ref, revenue, profit, ocf, capex, roe, margin = row
        for metric, value, unit, suffix in (
            ("合并营业收入", revenue, "亿元人民币", "revenue"),
            ("归母净利润", profit, "亿元人民币", "parent_profit"),
            ("经营现金流", ocf, "亿元人民币", "ocf"),
            ("固定资产现金资本开支", capex, "亿元人民币", "capex"),
            ("加权ROE", roe, "%", "roe"),
            ("综合毛利率", margin, "%", "gross_margin"),
        ):
            facts.append(
                _fact(
                    ref, "chint_company", metric, value, unit, year,
                    f"chint_{suffix}_{year}",
                    "公司合并口径；资本开支不包含作为存货核算的待转让项目建设。",
                )
            )

    q1_rows = (
        ("营业收入", 213.03, "亿元人民币"),
        ("归母净利润", 12.67, "亿元人民币"),
        ("经营现金流", 41.19, "亿元人民币"),
        ("收入同比增速", 46.33, "%"),
        ("归母净利润同比增速", 8.92, "%"),
    )
    for index, (metric, value, unit) in enumerate(q1_rows):
        facts.append(
            _fact(
                "r-chint-q12026", "chint_company", metric, value, unit,
                "2026Q1", f"chint_q1_2026_{index}",
                "一季度项目交割存在季节性，不能线性外推全年。",
            )
        )

    sales_modes = {
        "2023": {
            "户用光伏开发与合作运营": (47.33, 56.46),
            "户用电站转让": (243.97, 10.21),
            "自然人电站销售": (3.60, 5.61),
            "非户用EPC": (25.38, 9.15),
        },
        "2024": {
            "户用光伏开发与合作运营": (67.71, 53.30),
            "户用电站转让": (247.77, 10.97),
            "自然人电站销售": (0.39, 15.94),
            "非户用EPC": (60.21, 16.41),
        },
        "2025": {
            "户用光伏开发与合作运营": (99.60, 56.00),
            "户用电站转让": (183.07, 6.65),
            "自然人电站销售": (0.02, 8.97),
            "非户用EPC": (17.22, 23.29),
        },
    }
    refs = {"2023": "r-chint-ar2023", "2024": "r-chint-ar2024", "2025": "r-chint-ar2025"}
    for year, segments in sales_modes.items():
        for segment, (revenue, margin) in segments.items():
            key = segment.replace("与", "").replace("光伏", "")
            facts.extend(
                [
                    _fact(
                        refs[year], "chint_pv_business",
                        f"{segment}收入", revenue, "亿元人民币", year,
                        f"{key}_revenue_{year}",
                        "同一销售模式按年报披露口径，不与其他模式重复。",
                    ),
                    _fact(
                        refs[year], "chint_pv_business",
                        f"{segment}毛利率", margin, "%", year,
                        f"{key}_margin_{year}",
                        "毛利率对应该销售模式，不等于合并净利率。",
                    ),
                ]
            )

    aneng_financial = {
        "2022": (137.04, 17.53, 37.51, 76.92, 27.03, 395.61, 91.29),
        "2023": (296.06, 26.04, 24.87, 79.16, 0.23, 566.72, 118.11),
        "2024": (318.26, 28.61, 21.61, 80.25, 118.48, 742.57, 146.64),
    }
    for year, row in aneng_financial.items():
        for metric, value, unit, suffix in (
            ("正泰安能营业收入", row[0], "亿元人民币", "revenue"),
            ("正泰安能净利润", row[1], "亿元人民币", "profit"),
            ("正泰安能ROE", row[2], "%", "roe"),
            ("正泰安能资产负债率", row[3], "%", "liability_ratio"),
            ("正泰安能经营现金流", row[4], "亿元人民币", "ocf"),
            ("正泰安能总资产", row[5], "亿元人民币", "assets"),
            ("正泰安能归母净资产", row[6], "亿元人民币", "equity"),
        ):
            facts.append(
                _fact(
                    "r-aneng-ipo2025", "aneng_business", metric, value, unit,
                    year, f"aneng_{suffix}_{year}",
                    "招股书申报口径；经营现金流受项目结算时点显著影响。",
                )
            )

    business_series = {
        "合作开发与运营收入": [34.01, 43.82, 61.92],
        "电站销售收入": [100.52, 247.57, 248.16],
        "系统设备收入": [0.96, 0.03, 0.01],
        "售后运维收入": [1.07, 3.50, 5.80],
        "合作开发与运营毛利率": [59.93, 56.09, 54.74],
        "电站销售毛利率": [14.07, 10.09, 10.97],
        "系统设备毛利率": [6.04, 3.51, 9.88],
        "售后运维毛利率": [60.54, 61.11, 37.83],
        "合作运营装机容量": [9.72, 14.07, 19.29],
        "合作运营农户数量": [48.42, 61.90, 70.96],
        "第三方电站交付容量": [3.185, 8.060, 8.365],
        "有效运维容量": [1.599, 8.269, 16.021],
        "基础运维单价": [0.0398, 0.0387, 0.0386],
        "预计负债": [0.261, 1.215, 3.008],
        "存货周转率": [0.92, 1.10, 0.77],
        "速动比率": [0.27, 0.28, 0.28],
        "售后回租长期应付款": [30.24, 85.43, 98.07],
    }
    units = {
        "收入": "亿元人民币", "毛利率": "%", "装机容量": "GW",
        "农户数量": "万户", "交付容量": "GW", "运维容量": "GW",
        "运维单价": "元/W·年", "预计负债": "亿元人民币",
        "存货周转率": "次", "速动比率": "倍", "长期应付款": "亿元人民币",
    }
    years = ("2022", "2023", "2024")
    for metric, values in business_series.items():
        unit = next(value for key, value in units.items() if key in metric)
        for year, value in zip(years, values):
            facts.append(
                _fact(
                    "r-aneng-ipo2025", "aneng_business", metric, value, unit,
                    year, f"aneng_{metric}_{year}",
                    "同一指标的逐年披露用于观察结构变化；证据计数按指标口径去重。",
                )
            )

    discrete = [
        ("r-chint-ar2025", "chint_pv_business", "正泰安能2025年收入", 287.28, "亿元人民币", "2025", "aneng_revenue_2025"),
        ("r-chint-ar2025", "chint_pv_business", "正泰安能2025年净利润", 30.40, "亿元人民币", "2025", "aneng_profit_2025"),
        ("r-chint-ar2025", "chint_pv_business", "户用电站发电量保障或差额补偿规模", 27.0, "GW以上", "2025", "generation_support_2025"),
        ("r-chint-ar2025", "chint_pv_business", "年度获批户用电站出售上限", 14.0, "GW", "2025", "station_sale_authorization_2025"),
        ("r-chint-ar2025", "chint_company", "合并担保总额", 274.26, "亿元人民币", "2025", "guarantees_total_2025"),
        ("r-chint-ar2025", "chint_company", "担保总额占净资产", 61.63, "%", "2025", "guarantees_equity_ratio_2025"),
        ("r-chint-ar2025", "chint_company", "高负债率主体担保", 249.23, "亿元人民币", "2025", "guarantees_high_leverage_2025"),
        ("r-chint-ar2025", "chint_company", "农户光伏贷款担保", 8.89, "亿元人民币", "2025", "household_loan_guarantee_2025"),
        ("r-chint-ar2025", "chint_company", "投资收益", 7.14, "亿元人民币", "2025", "investment_income_2025"),
        ("r-chint-ar2025", "chint_company", "资产减值损失", 3.07, "亿元人民币", "2025", "asset_impairment_2025"),
        ("r-chint-ar2025", "chint_company", "存货增加对经营现金流影响", -125.67, "亿元人民币", "2025", "inventory_cash_effect_2025"),
        ("r-chint-ar2025", "chint_company", "经营性应付款增加对经营现金流影响", 235.14, "亿元人民币", "2025", "payables_cash_effect_2025"),
        ("r-aneng-ipo2025", "aneng_business", "2024年前五大客户收入占比", 71.83, "%", "2024", "top5_customer_share_2024"),
        ("r-aneng-ipo2025", "aneng_business", "2024年电站销售材料成本占比", 55.01, "%", "2024", "station_material_cost_share_2024"),
        ("r-aneng-ipo2025", "aneng_business", "2024年电站销售经销商安装开发成本占比", 44.80, "%", "2024", "station_dealer_cost_share_2024"),
        ("r-aneng-ipo2025", "aneng_business", "2024年运维成本中经销商运维占比", 94.19, "%", "2024", "dealer_om_cost_share_2024"),
        ("r-aneng-ipo2025", "aneng_business", "2024年发电量差额补偿净支出", 0.3809, "亿元人民币", "2024", "generation_shortfall_2024"),
        ("r-aneng-ipo2025", "aneng_business", "2022—2024累计发电量完成率", 102.0, "%", "2022—2024", "generation_attainment_2022_2024"),
        ("r-aneng-inquiry2", "household_risk_chain", "2023年末光伏贷款担保余额", 24.92, "亿元人民币", "2023", "pv_loan_guarantee_2023"),
        ("r-aneng-inquiry2", "household_risk_chain", "光伏贷款相关诉讼数量", 34, "件", "截至问询回复", "pv_loan_lawsuits"),
        ("r-aneng-inquiry1", "household_risk_chain", "2023年拆站户数", 1145, "户", "2023", "station_removal_households_2023"),
        ("r-aneng-inquiry1", "household_risk_chain", "2023年拆站容量", 16.42, "MW", "2023", "station_removal_capacity_2023"),
        ("w-ndrc-136", "policy_risk", "新能源上网电量市场化覆盖", "全面进入电力市场", "政策要求", "2025起", "market_pricing_policy"),
        ("w-nea-measures", "policy_risk", "非自然人户用项目备案主体", "不得以自然人名义备案", "政策要求", "2025起", "filing_identity_policy"),
        ("w-aneng-complaint-response", "household_contract_cashflow_case", "区域合作方合同电站容量", 75.0, "kW", "2024-05", "reported_contract_capacity"),
        ("w-aneng-complaint-response", "household_contract_cashflow_case", "区域合作方合同组件数量", 120, "块", "2024-05", "reported_contract_module_count"),
        ("w-aneng-complaint-response", "household_contract_cashflow_case", "区域合作方合同年租金", 1800, "元/年", "2024-05", "reported_contract_annual_rent"),
        ("w-zoucheng-court-rooftop-contract", "household_contract_cashflow_case", "司法合同组件数量", 62, "块", "2022补充协议", "judicial_contract_module_count"),
        ("w-zoucheng-court-rooftop-contract", "household_contract_cashflow_case", "司法合同年租金", 2170, "元/年", "2022补充协议", "judicial_contract_annual_rent"),
        ("w-zoucheng-court-rooftop-contract", "household_contract_cashflow_case", "司法合同每块组件年租金", 35, "元/块·年", "2022补充协议", "judicial_contract_rent_per_module"),
        ("w-zoucheng-court-rooftop-contract", "household_contract_cashflow_case", "司法合同11个月发电收益", 12455.21, "元", "2022-08至2023-06", "judicial_contract_11m_grid_revenue"),
        ("w-astronergy-n7-datasheet", "household_contract_cashflow_case", "正泰新能625W组件长度", 2382, "毫米", "2025-08", "n7_module_length"),
        ("w-astronergy-n7-datasheet", "household_contract_cashflow_case", "正泰新能625W组件宽度", 1134, "毫米", "2025-08", "n7_module_width"),
        ("w-weifang-court-electronic-contract", "household_contract_cashflow_case", "电子屋顶租赁合同约定违约金", 20000, "元", "2024", "court_contract_penalty"),
        ("w-weifang-court-electronic-contract", "household_contract_cashflow_case", "法院酌定实际违约金", 10000, "元", "2026-05", "court_awarded_penalty"),
        ("w-yuzhou-court-roof-leak", "household_contract_cashflow_case", "漏水纠纷屋顶租赁期限", 20, "年", "2023起", "roof_leak_case_term"),
        ("w-yuzhou-court-roof-leak", "household_contract_cashflow_case", "漏水纠纷企业主张各项损失", "近50万元", "案件金额", "2025-10", "roof_leak_claimed_loss"),
        ("w-baiyin-court-pv-loan", "household_contract_cashflow_case", "光伏贷案例农户月发电收益", 370, "元/月左右", "2018后", "pv_loan_monthly_revenue"),
        ("w-baiyin-court-pv-loan", "household_contract_cashflow_case", "光伏贷案例还款期限", "5—6年", "合同期限", "2018起", "pv_loan_repayment_term"),
        ("w-baiyin-court-pv-loan", "household_contract_cashflow_case", "光伏贷案例调整后上网收购标准", 0.4878, "元/kWh", "案件协调后", "pv_loan_adjusted_tariff"),
        ("w-aneng-stake", "chint_company", "正泰安能3.16%股权交易对价", 11.16, "亿元人民币", "2026-07", "aneng_stake_transaction_value"),
        ("w-aneng-stake", "chint_company", "交易后正泰电器持股比例", 71.24, "%", "2026-07", "aneng_stake_after_transaction"),
    ]
    for row in discrete:
        facts.append(_fact(*row, "用于约束业务、现金流、责任链或估值。", extraction_method="web_fetch" if str(row[0]).startswith("w-") else "pdf_direct"))

    model_rows = [
        ("2026年基准收入", 751.0, "亿元人民币", "2026", "model_revenue_2026"),
        ("2027年基准收入", 829.0, "亿元人民币", "2027", "model_revenue_2027"),
        ("2028年基准收入", 911.0, "亿元人民币", "2028", "model_revenue_2028"),
        ("2026年基准归母净利润", 54.9, "亿元人民币", "2026", "model_profit_2026"),
        ("2027年基准归母净利润", 66.4, "亿元人民币", "2027", "model_profit_2027"),
        ("2028年基准归母净利润", 78.3, "亿元人民币", "2028", "model_profit_2028"),
        ("独立估值严格交集下限", 29.38, "元/股", "2026-07-24", "model_price_low"),
        ("独立估值严格交集上限", 31.50, "元/股", "2026-07-24", "model_price_high"),
        ("基准模型2026年经营现金流", 91.5, "亿元人民币", "2026", "model_ocf_2026")
    ]
    for metric, value, unit, period, scope in model_rows:
        facts.append(
            _fact(
                "r-run15-model", "chint_company", metric, value, unit, period,
                scope, "本研究独立模型输出，输入和输出均已冻结。",
                extraction_method="inferred",
            )
        )
    household_model_rows = [
        ("统计代表站容量", 27.189, "kW", "2024统计尺度", "representative_capacity"),
        ("统计代表站年度发电量", 27315, "kWh/年", "2024统计尺度", "representative_generation"),
        ("统计代表站年度电网结算收入", 8725.96, "元/年", "2024统计尺度", "representative_grid_revenue"),
        ("按电站转让口径缩放的交易价值", 80659.27, "元", "2024统计尺度", "scaled_transfer_value"),
        ("按电站转让成本结构缩放的经销商安装开发成本", 32171.57, "元", "2024统计尺度", "scaled_dealer_cost"),
        ("基准情景融资后年度剩余现金", 1035.92, "元/年", "示例模型", "base_residual_after_debt"),
        ("发电量下降15%情景融资后年度剩余现金", -272.97, "元/年", "示例模型", "low_generation_residual_after_debt"),
        ("发电量下降15%且电价下降10%情景融资后年度剩余现金", -1014.68, "元/年", "示例模型", "low_generation_price_residual_after_debt"),
        ("停机30天并发生3000元维修情景融资后年度剩余现金", -2681.28, "元/年", "示例模型", "repair_residual_after_debt"),
        ("100平方米排布中值组件数量", 30, "块", "100平方米示例", "roof100_module_count"),
        ("100平方米排布中值装机容量", 18.75, "kW", "100平方米示例", "roof100_capacity"),
        ("100平方米按正泰合作运营均值缩放的年度电费", 6017.57, "元/年", "100平方米示例", "roof100_grid_revenue"),
        ("100平方米按15元每块合同的年度租金", 450, "元/年", "100平方米示例", "roof100_rent_15"),
        ("100平方米按35元每块司法合同的年度租金", 1050, "元/年", "100平方米示例", "roof100_rent_35"),
        ("100平方米按15元每块合同的融资后剩余现金", 1850.51, "元/年", "100平方米示例", "roof100_residual_after_debt"),
    ]
    for metric, value, unit, period, scope in household_model_rows:
        facts.append(
            _fact(
                "r-run15-household-contract-model",
                "household_contract_cashflow_case",
                metric,
                value,
                unit,
                period,
                scope,
                "本研究示例模型输出；公司披露、合同事实和研究假设已分层，不能当作单个真实项目收益承诺。",
                extraction_method="inferred",
            )
        )
    group_bridge_rows = [
        ("最低发电保障或差额补偿义务规模", 27.0, "GW", "2025", "minimum_guarantee_capacity"),
        ("27GW口径年化基础运维收入", 10.4220, "亿元人民币", "2025口径年化", "portfolio_basic_om_revenue"),
        ("27GW口径按2024年强度估算的年度净补偿", 0.6427, "亿元人民币", "2025口径年化", "portfolio_compensation"),
        ("27GW口径年化运维毛利润", 3.6995, "亿元人民币", "2025口径年化", "portfolio_om_gross_profit"),
        ("27GW口径运维归母利润上限", 2.1084, "亿元人民币", "2025口径年化", "portfolio_parent_profit_upper_bound"),
        ("2025年预计负债", 7.1620, "亿元人民币", "2025", "expected_liabilities_2025"),
        ("2025年预计负债同比增加", 3.9487, "亿元人民币", "2025", "expected_liabilities_increase_2025"),
        ("2026年组合风险情景对应股价", 22.41, "元/股", "2026", "risk_price_2026"),
        ("独立核心价值严格交集下沿", 29.38, "元/股", "2026-07-27", "core_price_low_20260727"),
        ("独立核心价值严格交集上沿", 31.50, "元/股", "2026-07-27", "core_price_high_20260727"),
    ]
    for metric, value, unit, period, scope in group_bridge_rows:
        facts.append(
            _fact(
                "r-run15-household-group-bridge",
                "chint_company",
                metric,
                value,
                unit,
                period,
                scope,
                (
                    "本研究把公司披露的组合责任、已冻结分业务模型与2026年7月27日"
                    "Wind单证券市场快照连接；市场数据仍只写入financial.db。"
                ),
                extraction_method="inferred",
            )
        )
    return facts


def build_data_points() -> list[dict[str, Any]]:
    sources = {row["ref"]: row for row in SOURCES}
    entity_map = {
        "chint_company": "chint_pv_business",
        "aneng_business": "chint_pv_business",
        "policy_risk": "household_risk_chain",
    }
    rows: list[dict[str, Any]] = []
    for index, spec in enumerate(build_fact_specs(), start=1):
        source = sources[spec["source_ref"]]
        point: dict[str, Any] = {
            "data_point_key": f"run15.chint.{index:03d}",
            "source_ref": spec["source_ref"],
            "entity_key": entity_map.get(
                spec["entity_key"], spec["entity_key"]
            ),
            "metric": spec["metric"],
            "unit": spec["unit"],
            "period": spec["period"],
            "scope_key": spec["scope_key"],
            "source_excerpt": source["excerpt"],
            "extraction_method": spec["extraction_method"],
            "note": spec["note"],
            "value_text": str(spec["value"]),
        }
        if isinstance(spec["value"], (int, float)):
            point["value_num"] = spec["value"]
        if source.get("language") != "zh":
            point["source_excerpt_zh"] = source.get(
                "excerpt_zh", source["excerpt"]
            )
        rows.append(point)
    return rows


def build_claims() -> list[dict[str, Any]]:
    specs = [
        ("chint_company", "r-chint-ar2025", "事实", "正泰电器2025年收入下降而归母净利润增长，业务组合变化比收入总额更重要。"),
        ("chint_pv_business", "r-chint-ar2025", "事实", "2025年户用合作运营收入99.60亿元、毛利率56.00%，户用电站转让收入183.07亿元、毛利率仅6.65%。"),
        ("chint_pv_business", "r-aneng-ipo2025", "分析", "正泰安能通过开发转让获取周转利润，通过合作运营和运维获取长期利润，两条路径的现金回收和尾部责任不同。"),
        ("chint_company", "r-chint-ar2025", "事实", "2025年经营现金流显著受经营性应付款增加和项目存货变化影响，不能直接作为稳定现金创造能力。"),
        ("household_risk_chain", "r-aneng-inquiry2", "事实", "历史光伏贷由发电收益偿还，正泰安能或关联方提供担保，风险并非全部留在农户。"),
        ("household_risk_chain", "w-jiangyin-warning", "反证", "地方政府提示的农户融资、收益权质押和合同风险是行业通用风险，不能据此认定正泰安能存在同样违规。"),
        ("policy_risk", "w-nea-measures", "事实", "2025年管理办法加强备案主体、建设和运维责任，压缩以自然人名义替非自然人备案的空间。"),
        ("policy_risk", "w-ndrc-136", "事实", "新能源电量全面市场化使增量项目电价和消纳不确定性上升。"),
        ("chint_company", "r-run15-model", "推断", "独立模型基准情景预计2026—2028年归母净利润为54.9、66.4、78.3亿元。"),
        ("chint_company", "r-run15-reconciliation", "分析", "独立模型收入比五份近期报告中位数高18.74%—24.86%，净利润高4.71%—10.08%，差异主要是低毛利电站转让量。"),
        ("chint_company", "r-run15-model", "估值", "PE、分部估值和PB—ROE的严格交集为29.38—31.50元/股；核心下限取各方法下限最大值，上限取各方法上限最小值，不做机械平均。"),
        ("household_risk_chain", "w-aneng-complaint-response", "线索", "个别屋顶投诉显示代理商管理和售后可能产生声誉风险，但单一报道不足以推断系统性质量问题。"),
        ("household_contract_cashflow_case", "r-aneng-ipo2025", "事实", "正泰安能企业投资模式下，电网电费进入运营主体账户并向农户支付租金；电站出售后，资产买方重新与农户签约并承接后续收益与租金。"),
        ("household_contract_cashflow_case", "w-cpia-household-contract-template", "合同", "标准合同把电费账户、资产所有权、农户收益、运营运维、漏水、拆迁和违约责任分开约定，宣传中的“零出资”不能替代这些条款。"),
        ("household_contract_cashflow_case", "w-weifang-court-electronic-contract", "司法案例", "屋顶租赁电子合同在签署流程可靠时具有法律效力，农户擅自拆除投资方设备可能承担返还和违约责任。"),
        ("household_contract_cashflow_case", "w-yuzhou-court-roof-leak", "司法案例", "农户不得擅自剪线或阻碍发电，施工运营方也需要修复施工导致的漏水并承担后续质保，责任不是单向转嫁。"),
        ("household_contract_cashflow_case", "w-baiyin-court-pv-loan", "反证", "当农户是贷款借款人时，发电收益不足会直接形成农户偿债缺口；企业投资租赁模式与光伏贷不能混为一谈。"),
        ("household_contract_cashflow_case", "w-zoucheng-court-rooftop-contract", "司法案例", "一份真实合同按62块组件、35元/块·年支付2170元租金，11个月电费合计12455.21元；结算卡名义归农户但由投资企业控制，账户控制本身就是履约风险。"),
        ("household_contract_cashflow_case", "w-astronergy-n7-datasheet", "产品事实", "当前625W组件外形为2382×1134毫米；100平方米屋顶理论上限约37块，预留检修和边界后以30块、18.75kW作为可复算中值，不构成工程承诺。"),
        ("household_contract_cashflow_case", "r-run15-household-contract-model", "推断", "27.19kW统计代表站在示例融资结构下基准偿债覆盖1.24倍，发电量下降15%后降至0.94倍，固定租金会优先保护农户、把经营偏差留给资产持有方。"),
        ("household_contract_cashflow_case", "r-run15-household-group-bridge", "分析", "100平方米案例只识别一份合同的现金与责任归属，不能把一次屋顶维修损失机械乘到全部27GW；组合层必须用公司披露的运维费率、补偿强度和预计负债校准。"),
        ("chint_company", "r-run15-household-group-bridge", "推断", "按超过27GW保障义务、2024年每瓦运维费和实际补偿强度缩放，年化净运维收入约9.78亿元、毛利润约3.70亿元；归母利润上限约2.11亿元，不能当作精确净利润预测。"),
        ("chint_company", "r-run15-household-group-bridge", "估值", "截至2026年7月27日，24.57元只适合小仓位观察；22—23元且现金流、存货和预计负债未恶化时，分批买入的风险收益更合理。"),
    ]
    sources = {row["ref"]: row for row in SOURCES}
    entity_map = {
        "chint_company": "chint_pv_business",
        "policy_risk": "household_risk_chain",
    }
    claims = []
    for index, (entity, ref, claim_type, text) in enumerate(specs, start=1):
        claim = {
                "claim_id": f"run15.claim.{index:03d}",
                "entity_key": entity_map.get(entity, entity),
                "source_ref": ref,
                "claim_type": claim_type,
                "claim_text": text,
                "source_excerpt": sources[ref]["excerpt"],
            }
        if sources[ref].get("language") != "zh":
            claim["source_excerpt_zh"] = sources[ref].get(
                "excerpt_zh", sources[ref]["excerpt"]
            )
        claims.append(claim)
    return claims
