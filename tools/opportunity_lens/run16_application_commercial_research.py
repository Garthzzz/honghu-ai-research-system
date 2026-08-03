from __future__ import annotations

"""Quantified AI-application commercialization ledger for Opportunity Lens Run16.

The public report consumes these records as research conclusions, not as a source
of accounting facts.  Every calculation that uses an undisclosed price or labour
cost is labelled as a sensitivity rather than a company disclosure.
"""

from typing import Any


APPLICATION_COMMERCIAL_RESEARCH: tuple[dict[str, Any], ...] = (
    {
        "company": "金山办公",
        "ticker": "688111.SH",
        "model_ready": True,
        "buyer_and_evidence": (
            "个人会员付订阅费，组织客户按席位或授权付费。2025年WPS 365收入7.20亿元、"
            "同比增长64.93%；官网商业协作/高级/旗舰版标价为199/399/599元/人/年。"
        ),
        "buyer_value_math": (
            "由协作版升到高级版或旗舰版，每100万席位按公开标价对应2.00亿元或4.00亿元"
            "年收入增量；大客户折扣、部署费和推理成本未披露，因此这只是席位敏感性。"
        ),
        "market_and_model_test": (
            "财务模型不能把WPS 365收入全部算作AI增量；必须分别检验席位净增、版本升级、"
            "续费率与推理成本。由于公司未完整披露这些变量，本轮以公司总收入、利润率和"
            "现金转换桥接，并把企业席位升级作为上行情景而非基准事实。"
        ),
        "investment_view": (
            "产品入口、订阅质量和现金创造能力均强，但高质量公司不自动等于当前价格可买。"
            "投资动作以同一版冻结模型生成的利润、现金流和估值对账为准，不再在商业证据"
            "底稿中保留可能随模型更新而失效的目标市值。"
        ),
        "refs": ("app-c01", "app-c02", "app-c23"),
    },
    {
        "company": "合合信息",
        "ticker": "688615.SH",
        "model_ready": True,
        "buyer_and_evidence": (
            "个人用户付扫描、识别和数据服务订阅；银行、制造、医药等企业为API、私有化"
            "文档解析和合同/知识库项目付费。TextIn披露超过1,000家企业客户和10亿页处理量，"
            "并有建信信托、东方希望、泰格医药等具名部署。"
        ),
        "buyer_value_math": (
            "客户购买的是减少录入、审单和合同处理工时及降低差错风险，但公开资料没有项目"
            "价格和续费率。不能把1,000家客户平均化；更可靠的验证是同一客户从单API扩展到"
            "知识库、合同、财报等多个场景后，B端单客收入和毛利是否同步上升。"
        ),
        "market_and_model_test": (
            "增长不能只用企业客户数量外推；基准模型同时依赖C端订阅、B端多场景扩单和"
            "稳定现金转换。B端单客收入、续费和私有化项目占比若没有提高，客户覆盖数量"
            "本身不足以支持利润持续快于收入增长。"
        ),
        "investment_view": (
            "个人订阅、文档数据处理和企业私有化形成了比多数AI应用更清楚的付费闭环。"
            "当前是否具有安全边际由冻结模型动态计算；经营上最重要的上修条件是B端单客"
            "价值和续费提高，而不是案例数量继续增加。"
        ),
        "refs": ("app-c03", "app-c04", "app-c21", "app-c27"),
    },
    {
        "company": "同花顺",
        "ticker": "300033.SZ",
        "model_ready": True,
        "buyer_and_evidence": (
            "个人投资者为增值服务付费，券商和机构为行情、数据、iFind和工作流付费。公司"
            "已把AI嵌入i问财等产品，但2025年没有单列AI收入、AI套餐价格或AI续费数据。"
        ),
        "buyer_value_math": (
            "AI能否收费应由客单价、付费转化和留存验证；2025年收入增长44%、利润增长75.79%"
            "同时处在资本市场活跃期，不能把成交额上升带来的广告和增值服务收入记作AI贡献。"
        ),
        "market_and_model_test": (
            "基准模型把资本市场活跃度作为基础业务变量，并假设利润率从周期高位回落。"
            "由于公司没有单列AI价格、付费账户或合同，AI提价不能重复计入基准收入，只能"
            "在可核验付费和留存出现后进入上行情景。"
        ),
        "investment_view": (
            "数据、流量和高利润率构成优质业务，但股价不能把成交周期上行与AI商业化重复"
            "定价。投资动作由最新冻结模型的正常化利润和估值区间决定；没有独立AI付费"
            "证据时，不额外给予AI估值溢价。"
        ),
        "refs": ("app-c05", "app-c06"),
    },
    {
        "company": "科大讯飞",
        "ticker": "002230.SZ",
        "model_ready": True,
        "buyer_and_evidence": (
            "教育由学校和区域教育部门采购，医疗和政务由机构或政府采购，MaaS/API由开发者"
            "和企业按调用付费。2025年AI平台收入12.52亿元、MaaS/API收入3.85亿元；智慧教育"
            "覆盖5万余所学校，但付费学校、AI升级金额和续费未披露。"
        ),
        "buyer_value_math": (
            "学校覆盖是渠道，不是收入。智能批阅机已进入260多所学校、服务3,800多位教师；"
            "若每位教师每周仅节省1小时、每年40周、综合时间价值100—200元/小时，对应"
            "1,520万—3,040万元年客户价值。设备、维护和算力价格未披露，所以这里只给"
            "全体已部署教师的付费上限敏感性，不把80%效率宣称直接当财务事实。"
        ),
        "market_and_model_test": (
            "AI平台收入增长只能解释公司总收入增量的一部分。模型的核心约束不是学校覆盖"
            "数量，而是项目验收、回款、研发与资本开支之后能否形成持续自由现金流；渠道"
            "覆盖在没有付费金额和续费率时不直接进入利润预测。"
        ),
        "investment_view": (
            "收入证据在应用公司中较直接，但低ROE、项目回款和资本投入限制估值。当前动作"
            "以冻结模型的现金流与估值对账为准；学校覆盖数量不作为买入理由，只有AI收入"
            "增长同时转成自由现金流才支持更高估值。"
        ),
        "refs": ("app-c07", "app-c08", "app-c32", "app-c34"),
    },
    {
        "company": "鼎捷数智",
        "ticker": "300378.SZ",
        "model_ready": True,
        "buyer_and_evidence": (
            "制造企业为ERP/MES/PLM、数据套件和工业智能体项目付费。2025年AI相关签约近2亿元，"
            "约为当年24.33亿元收入的8.2%，覆盖汽配、装备、电子、家电和化工；这是应用组"
            "最清楚的AI合同金额之一。"
        ),
        "buyer_value_math": (
            "若其中70%在未来12—18个月验收，按58.55%毛利率、实施和销售增量成本占收入"
            "25%—35%、所得税15%测算，2亿元合同可贡献约0.28—0.40亿元增量净利润；这才是"
            "合同到利润的合理量级，而不是直接把2亿元加到利润。"
        ),
        "market_and_model_test": (
            "首批AI合同只能解释一部分收入增长，剩余增量仍需续签、跨行业复制和基础软件"
            "恢复。2026年一季度收入仅增长3.02%且亏损，说明签约到验收、收入和利润之间"
            "仍有明显时滞，不能用合同金额直接替代盈利预测。"
        ),
        "investment_view": (
            "工业流程和明确合同提高研究价值，但投资上行来自合同连续转成利润并提高实施"
            "人效，不来自‘工业AI稀缺’标签。当前动作以更新后的冻结模型为准；商业证据"
            "较强也不能覆盖利润增速、ROE或估值不合格。"
        ),
        "refs": ("app-c09", "app-c10", "app-c24"),
    },
    {
        "company": "深信服",
        "ticker": "300454.SZ",
        "model_ready": True,
        "buyer_and_evidence": (
            "政企客户为安全产品、托管运营、私有化Agent和云平台付费。公司披露安全运营手工"
            "操作减少92%、MTTD/MTTR减少85%；匿名制造客户把单份合同审查从5小时降至5分钟。"
        ),
        "buyer_value_math": (
            "按每年2,000份合同、每小时100—200元综合法务成本测算，可释放约9,833小时，"
            "对应98万—197万元年人力价值；若许可、部署和复核总成本低于50万—100万元，"
            "客户静态回收期约0.25—1.02年。实际售价未披露，这只是客户愿付上限的检验。"
        ),
        "market_and_model_test": (
            "由于AI收入没有单列，单个Agent案例不能解释公司未来总收入增长。模型重点检验"
            "标准化产品能否降低交付和销售费用率，并把较高研发投入转成续费和自由现金流；"
            "效率案例只证明客户价值，不证明公司已获得相应利润。"
        ),
        "investment_view": (
            "安全工作流的责任和持续运营支持收费，但公司仍需证明AI续费、单客价值和费用率"
            "改善。投资动作以最新冻结模型的利润和估值为准；不能仅凭效率案例为全部业务"
            "恢复支付高估值。"
        ),
        "refs": ("app-c11", "app-c12", "app-c25", "app-c26"),
    },
    {
        "company": "用友网络",
        "ticker": "600588.SH",
        "model_ready": False,
        "buyer_and_evidence": (
            "大型企业和央国企为BIP、财务、人力、采购、制造和AI平台项目付费。2025年AI相关"
            "合同16.7亿元、约为收入的18.2%，部分单笔超过千万元；2026年上半年又披露中船、"
            "三峡、中粮、招商局、中国有研等签约、启动或上线项目。"
        ),
        "buyer_value_math": (
            "按16.7亿元合同、49.6%毛利率、实施销售增量成本占收入25%—35%、所得税25%测算，"
            "整批合同的理论增量净利润约1.83—3.08亿元，仍远小于2025年13.89亿元亏损。"
        ),
        "market_and_model_test": (
            "AI合同证明需求，但不足以单独完成盈亏平衡；必须同时降低实施成本、人员费用和"
            "无形资产摊销，并把一次性项目转成ARR。签约、启动、上线三种状态必须分别跟踪，"
            "不能把客户名单全部视为新增合同。"
        ),
        "investment_view": (
            "亏损期PE没有意义，当前更适合用收入、ARR、经营现金流和盈亏平衡时间判断。"
            "在扣非利润转正并证明AI合同有重复续费前，不进入精确组合；若只见合同增长而"
            "亏损和应收不收敛，应把它视为交付负担而不是估值催化。"
        ),
        "refs": ("app-c13", "app-c14", "app-c28", "app-c29"),
    },
    {
        "company": "恒生电子",
        "ticker": "600570.SH",
        "model_ready": False,
        "buyer_and_evidence": (
            "券商、银行、基金和信托为核心交易、财富管理和智能体升级付费。善策六类投顾"
            "智能体已在20多家机构上线；恒生财富管理客户基础超过600家，当前公开渗透约3%"
            "量级，但上线不等于新增付费。"
        ),
        "buyer_value_math": (
            "若每家机构AI增购100万—300万元，20家仅对应0.20—0.60亿元收入；即使扩到100家，"
            "也只有1—3亿元。相对2025年57.83亿元收入，AI需要更大客户覆盖或更高续费，"
            "才能抵消传统金融IT收入下降。"
        ),
        "market_and_model_test": (
            "2025年收入下降12.13%，研发21.80亿元、占收入37.70%。因此当前最重要的模型不是"
            "给AI高倍数，而是判断20多家上线能否转成收费、能否在存量600多家客户复制，"
            "以及复用组件能否降低研发和交付成本。"
        ),
        "investment_view": (
            "先把它视为拥有分发渠道的早期商业化候选。只有基础收入止跌、AI付费机构数和"
            "客单价可核验、研发费用率下降，才进入FY1—FY3估值；否则投资收益改善不能替代"
            "主营收入和现金利润。"
        ),
        "refs": ("app-c18", "app-c30"),
    },
    {
        "company": "宝信软件",
        "ticker": "600845.SH",
        "model_ready": False,
        "buyer_and_evidence": (
            "钢铁企业为MES、自动化、工业互联网和垂直模型项目付费。公司列出鞍钢、马钢、"
            "重庆钢铁、华菱等二十余家MES客户，并称合同兑现率通常提高3%—5%、部分产品"
            "废品率下降0.05个百分点。"
        ),
        "buyer_value_math": (
            "以年产500万吨的钢厂为例，废品率下降0.05个百分点等于减少2,500吨废品；按"
            "吨钢3,000—4,000元估算，年直接产值保全约750万—1,000万元（0.075—0.100亿元），"
            "尚未计入交付改善。"
            "项目总价低于该价值的一部分时客户有经济性，但实际合同和归因未披露。"
        ),
        "market_and_model_test": (
            "MES的客户价值明确，却不能全部归因于生成式AI；宝信还混合自动化工程和数据"
            "中心业务。要进入模型，需拆分AI新增模块价格、项目毛利、关联客户、验收和回款，"
            "避免把钢铁数字化总效益全记到AI。"
        ),
        "investment_view": (
            "它比没有生产系统入口的通用AI公司更有壁垒，但商业验证应看新模块收入和项目"
            "现金回款。完成分部财务和估值前只作工业AI对照，不因客户名单和节省产值直接"
            "给组合权重。"
        ),
        "refs": ("app-c19", "app-c31"),
    },
    {
        "company": "广联达",
        "ticker": "002410.SZ",
        "model_ready": False,
        "buyer_and_evidence": (
            "设计院、施工和造价单位为设计、算量、造价和项目管理软件付费。2025年上半年"
            "AI直接合同超过0.40亿元，高速公路算量AI+BIM收入增长68.49%，部分岗位任务"
            "效率约提高10倍。"
        ),
        "buyer_value_math": (
            "0.40亿元直接合同已经证明收费。公司案例进一步给出设计—算量链路时间缩短"
            "12.1%、算量效率提高55%以上；PMSmart服务500多个项目，称平均每项目创效"
            "50万—100万元，对应客户侧总价值敏感性2.50亿—5.00亿元。这个数远高于已披露"
            "AI合同，说明有支付空间，也说明公司尚未把全部客户价值变成收入。"
        ),
        "market_and_model_test": (
            "当前证据能支持AI从功能进入合同和细分收入，但规模仍不足以决定公司整体业绩。"
            "模型应把建筑周期、基础造价业务和AI增购拆开，并用合同转收入率、单项目软件"
            "收入、续费和毛利改善验证AI是否抵消行业下行；供应商案例不能替代独立审计。"
        ),
        "investment_view": (
            "在AI合同连续两个报告期扩大且转成高毛利收入前，只列垂直软件观察候选。"
            "若合同增长但总收入、经营现金流和续费没有改善，说明AI只是产品防守，不是"
            "新的利润曲线。"
        ),
        "refs": ("app-c20", "app-c22", "app-c35"),
    },
    {
        "company": "万兴科技",
        "ticker": "300624.SZ",
        "model_ready": False,
        "buyer_and_evidence": (
            "全球个人和小团队为视频、图片和创意工具订阅付费。2025年AI原生应用收入超过"
            "1.30亿元、约占总收入8.5%，同比增长超过90%；这是比调用量更可靠的收费证据。"
        ),
        "buyer_value_math": (
            "公司2025年预计亏损0.65—0.95亿元。若AI新增收入扣除模型、渠道、营销和支持后"
            "贡献利润率为50%，还需额外1.30—1.90亿元AI收入才能单独填平亏损，约等于再造"
            "1.0—1.5个现有AI原生业务规模。"
        ),
        "market_and_model_test": (
            "AI原生业务已过收费门槛，但2026Q1总收入同比下降2.87%，说明新品增长仍被旧产品"
            "调整和成本拖累。下一步应同时看AI订阅续费、推理成本、获客费用和总公司自由"
            "现金流，而不是继续用调用次数证明商业化。"
        ),
        "investment_view": (
            "它是高弹性而非高确定性标的。扣非利润与自由现金流转正之前PE无意义；若AI原生"
            "收入接近2.6—3.2亿元且贡献利润率不降，才可能形成盈亏平衡拐点并进入精确估值。"
        ),
        "refs": ("app-c15", "app-c16", "app-c33"),
    },
)


def application_rows() -> tuple[dict[str, Any], ...]:
    return APPLICATION_COMMERCIAL_RESEARCH


def calculation_audit() -> dict[str, float]:
    """Recompute decision-relevant public sensitivities in their displayed units.

    Returns:
        Values in 亿元人民币, 万元人民币, hours, or years as encoded in
        each key. These are research sensitivities, not company disclosures.
    """

    contract_review_hours = 2_000 * (5 - 5 / 60)
    return {
        "wps_1m_seat_advanced_increment_100m_cny": 1_000_000 * (399 - 199) / 1e8,
        "wps_1m_seat_flagship_increment_100m_cny": 1_000_000 * (599 - 199) / 1e8,
        "digiwin_low_incremental_profit_100m_cny": 2 * 0.70 * (0.5855 - 0.35) * 0.85,
        "digiwin_high_incremental_profit_100m_cny": 2 * 0.70 * (0.5855 - 0.25) * 0.85,
        "iflytek_teacher_value_low_100m_cny": 3_800 * 1 * 40 * 100 / 1e8,
        "iflytek_teacher_value_high_100m_cny": 3_800 * 1 * 40 * 200 / 1e8,
        "sangfor_contract_review_hours": contract_review_hours,
        "sangfor_low_labor_value_10k_cny": contract_review_hours * 100 / 1e4,
        "sangfor_high_labor_value_10k_cny": contract_review_hours * 200 / 1e4,
        "yonyou_low_incremental_profit_100m_cny": 16.7 * (0.496 - 0.35) * 0.75,
        "yonyou_high_incremental_profit_100m_cny": 16.7 * (0.496 - 0.25) * 0.75,
        "hundsun_20_client_low_revenue_100m_cny": 20 * 1_000_000 / 1e8,
        "hundsun_20_client_high_revenue_100m_cny": 20 * 3_000_000 / 1e8,
        "baosight_low_scrap_value_100m_cny": 5_000_000 * 0.0005 * 3_000 / 1e8,
        "baosight_high_scrap_value_100m_cny": 5_000_000 * 0.0005 * 4_000 / 1e8,
        "glodon_project_value_low_100m_cny": 500 * 500_000 / 1e8,
        "glodon_project_value_high_100m_cny": 500 * 1_000_000 / 1e8,
        "wondershare_low_breakeven_revenue_100m_cny": 0.65 / 0.50,
        "wondershare_high_breakeven_revenue_100m_cny": 0.95 / 0.50,
    }
