from __future__ import annotations

"""Build the policy/geopolitics ledger used by lithium-battery research.

The ledger separates enacted rules, reported company exposure, and researcher
scenario inputs.  Reported overseas revenue is never silently treated as U.S.
direct exports or as taxable/export-rebate-eligible battery revenue.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_policy_scenarios_v1.json"
)


def _sha(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


POLICIES: list[dict[str, Any]] = [
    {
        "policyId": "cn_battery_consumption_tax_2026",
        "jurisdiction": "中国",
        "status": "已公告，2026年9月1日起执行",
        "rule": (
            "锂原电池、锂离子蓄电池等自2026年9月1日起按2%征收消费税，"
            "自2027年9月1日起按4%征收；连续生产应税电池可按规定扣除已缴消费税。"
        ),
        "technologyExemption": (
            "符合国家标准并取得合格检测报告的钠离子、固态和燃料电池，"
            "2026年9月1日至2028年12月31日免征。"
        ),
        "sourceTitle": "财政部 海关总署 税务总局公告2026年第20号",
        "sourceUrl": "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5251171/content.html",
        "sourceType": "中国税务总局政策原文",
        "modelFormula": (
            "消费税现金影响＝公司收入×国内应税收入比例×全年等效税率"
            "×（1－向客户转嫁比例）×（1－上游已税投入抵扣比例）"
        ),
        "annualEquivalentRate": {"2026": 0.0066666667, "2027": 0.0266666667, "2028": 0.04},
        "boundary": (
            "全年等效率按收入均匀发生近似；真实申报按应税销售额、纳税环节、"
            "实际抵扣和合同调价执行，不能直接套用集团总收入。"
        ),
    },
    {
        "policyId": "cn_export_vat_rebate_2026",
        "jurisdiction": "中国",
        "status": "已执行",
        "rule": (
            "电池产品出口退税率自2026年4月1日至12月31日由9%降至6%，"
            "2027年1月1日起取消；出口消费税退免政策不变。"
        ),
        "sourceTitle": "财政部 税务总局公告2026年第2号",
        "sourceUrl": "https://szs.mof.gov.cn/zhengcefabu/202601/t20260109_3981637.htm",
        "sourceType": "中国财政部政策原文",
        "modelFormula": (
            "退税减少现金影响＝公司收入×符合清单的出口收入比例"
            "×全年等效退税减少率×（1－向客户转嫁比例）"
        ),
        "annualEquivalentRate": {"2026": 0.0225, "2027": 0.09, "2028": 0.09},
        "boundary": (
            "2026年的2.25%是将4—12月每期减少3个百分点按全年收入均匀化；"
            "若输入本身只含4—12月出口收入，应直接使用3%。"
        ),
    },
    {
        "policyId": "us_clean_vehicle_credit_end_2025",
        "jurisdiction": "美国",
        "status": "已执行",
        "rule": (
            "30D新车、25E二手车和45W商用清洁车辆抵免不再适用于"
            "2025年9月30日之后取得的车辆。"
        ),
        "sourceTitle": "IRS Clean vehicle tax credits",
        "sourceUrl": "https://www.irs.gov/clean-vehicle-tax-credits",
        "sourceType": "美国国税局",
        "modelFormula": (
            "需求影响＝美国相关电池收入×美国电动车销量情景变化；"
            "不得把原车辆抵免金额直接从电芯ASP中扣除。"
        ),
        "boundary": "需求弹性需由车型、客户、库存和其他州级激励另行判断。",
    },
    {
        "policyId": "us_section_301_battery_tariff",
        "jurisdiction": "美国",
        "status": "已执行",
        "rule": (
            "中国锂离子电动车电池自2024年起为25%关税，"
            "非电动车锂离子电池自2026年起升至25%。"
        ),
        "sourceTitle": "USTR Section 301 statutory four-year review action",
        "sourceUrl": (
            "https://ustr.gov/about-us/policy-offices/press-office/press-releases/"
            "2024/may/us-trade-representative-katherine-tai-take-further-action-"
            "china-tariffs-after-releasing-statutory"
        ),
        "sourceType": "美国贸易代表办公室",
        "modelFormula": (
            "关税经济影响＝公司收入×美国直接出口比例×25%"
            "×由供应商承担的比例"
        ),
        "boundary": (
            "关税法律支付方通常是进口商，最终经济承担由议价、转口、本地化和"
            "客户替代决定；海外总收入不能替代美国直接出口收入。"
        ),
    },
    {
        "policyId": "us_45x_and_pfe",
        "jurisdiction": "美国",
        "status": "45X有效，但PFE限制已收紧",
        "rule": (
            "符合条件的美国本土电芯抵免35美元/kWh，含电芯模组10美元/kWh，"
            "不含电芯模组45美元/kWh；2030—2032年按75%/50%/25%退坡。"
        ),
        "sourceTitle": "IRS final regulations under section 45X",
        "sourceUrl": "https://www.irs.gov/irb/2024-51_IRB",
        "pfeSourceTitle": "IRS Notice 2026-15",
        "pfeSourceUrl": "https://www.irs.gov/irb/2026-11_IRB",
        "sourceType": "美国国税局法规与实施指引",
        "modelFormula": (
            "45X现金抵免＝合资格美国本地产量GWh×每kWh抵免美元"
            "×美元兑人民币÷100×产能利用率×资格实现比例"
        ),
        "boundary": (
            "中国企业的所有权、有效控制、技术许可和材料援助可能触发PFE限制；"
            "未核实具体项目资格前，45X只能放在条件上行情景，不能进入基准利润。"
        ),
    },
    {
        "policyId": "eu_battery_regulation",
        "jurisdiction": "欧盟",
        "status": "分阶段执行",
        "rule": (
            "相关电动车、轻型交通工具及2kWh以上工业电池自2027年2月18日起"
            "需要电池护照；电池尽职调查义务推迟至2027年8月18日。"
        ),
        "sourceTitle": "EU Batteries Regulation 2023/1542",
        "sourceUrl": "https://eur-lex.europa.eu/eli/reg/2023/1542/oj?locale=en",
        "dueDiligenceSourceTitle": "Council stop-the-clock act",
        "dueDiligenceSourceUrl": (
            "https://www.consilium.europa.eu/en/press/press-releases/2025/07/18/"
            "simplification-council-adopts-law-to-stop-the-clock-on-due-diligence-"
            "rules-for-batteries/"
        ),
        "sourceType": "欧盟法规及理事会最终立法说明",
        "modelFormula": (
            "合规现金影响＝系统改造、追溯、审计和认证资本开支"
            "＋持续运营费用；不得简单按收入统一扣点。"
        ),
        "boundary": (
            "义务承担主体与产品投放方式有关；成本可能由电芯厂、整车厂、"
            "进口商或当地合资实体分担。"
        ),
    },
    {
        "policyId": "eu_battery_booster_2026",
        "jurisdiction": "欧盟",
        "status": "已设立，预计2026年三季度征集",
        "rule": (
            "Battery Booster Facility提供总额15亿欧元无息贷款，"
            "单项目最高5亿欧元；项目须在欧洲经济区、最低10GWh并面向适用EV电池技术。"
        ),
        "sourceTitle": "European Commission Battery Booster Facility",
        "sourceUrl": (
            "https://climate.ec.europa.eu/eu-action/eu-funding-climate-action/"
            "innovation-fund/battery-booster-facility_en"
        ),
        "sourceType": "欧盟委员会",
        "modelFormula": "年度融资节约＝实际获批无息贷款×替代市场融资利率",
        "boundary": (
            "无息贷款改善融资成本而非制造成本；只有获批、提款和完成里程碑后"
            "才能计入现金流，不能预先计作营业收入或补贴利润。"
        ),
    },
    {
        "policyId": "eu_china_bev_duties",
        "jurisdiction": "欧盟",
        "status": "已执行",
        "rule": "中国生产的纯电动车反补贴税率按企业为7.8%—35.3%。",
        "sourceTitle": "European Commission definitive countervailing duties",
        "sourceUrl": (
            "https://ec.europa.eu/commission/presscorner/api/files/document/"
            "print/en/ip_24_5589/IP_24_5589_EN.pdf"
        ),
        "sourceType": "欧盟委员会",
        "modelFormula": (
            "间接电池影响＝受税车型欧洲销量变化×单车带电量×电池供货份额×ASP；"
            "BYD等整车电池一体化公司需先经过整车销量传导。"
        ),
        "boundary": "欧盟整车反补贴税不是对所有中国电芯直接加征同一税率。",
    },
    {
        "policyId": "cn_lithium_battery_norm_2024",
        "jurisdiction": "中国",
        "status": "现行行业规范",
        "rule": (
            "2024年版锂离子电池行业规范条件以技术、质量、安全、能耗、"
            "环保和资源综合利用约束项目，不把单纯扩大名义产能作为鼓励方向。"
        ),
        "sourceTitle": "锂离子电池行业规范条件（2024年本）",
        "sourceUrl": (
            "https://www.miit.gov.cn/zwgk/zcwj/wjfb/gg/art/2024/"
            "art_dfe849c6837c4a50bf3e3c30d1697710.html"
        ),
        "sourceType": "工业和信息化部",
        "modelFormula": (
            "规范条件本身不直接形成补贴收入；通过有效产能比例、合规资本开支、"
            "良率和项目退出概率进入供给模型。"
        ),
        "boundary": "规范条件是行业管理与引导，不等于所有入列企业获得订单或利润。",
    },
    {
        "policyId": "cn_storage_capacity_price_2026",
        "jurisdiction": "中国",
        "status": "已发布",
        "rule": (
            "符合条件的电网侧独立新型储能可按顶峰能力和放电时长折算容量电价，"
            "并与现货市场和可靠容量补偿衔接。"
        ),
        "sourceTitle": "关于完善发电侧容量电价机制的通知",
        "sourceUrl": "https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=20602",
        "sourceType": "国家发展改革委、国家能源局",
        "modelFormula": (
            "储能电芯需求影响＝新增合资格储能功率×配置时长÷系统效率"
            "×项目落地比例；政策不直接增加电芯厂每Wh毛利。"
        ),
        "boundary": "容量电价改善项目收入确定性，但实际需求仍取决于各地细则、并网和融资。",
    },
    {
        "policyId": "cn_ev_battery_recycling_2026",
        "jurisdiction": "中国",
        "status": "2026年4月1日起施行",
        "rule": (
            "动力电池回收新规强化电池生产、整车、维修、换电和回收主体的"
            "全链条责任与信息追溯。"
        ),
        "sourceTitle": "新能源汽车废旧动力电池回收和综合利用管理暂行办法",
        "sourceUrl": (
            "https://www.miit.gov.cn/gyhxxhb/jgsj/cyzcyfgs/bmgz/jdcjxl/"
            "art/2026/art_392462fdc40c415ea4a4129cac3028c2.html"
        ),
        "sourceType": "工业和信息化部等六部门",
        "modelFormula": (
            "回收净现金＝可获得废料量×单位回收价差－回收处理、物流、追溯和"
            "合规成本；没有废料来源时不按回收名义产能计利润。"
        ),
        "boundary": "生产者责任先增加合规投入，稳定废料来源和回收效率形成后才可能成为利润池。",
    },
    {
        "policyId": "cn_battery_material_export_control_2025",
        "jurisdiction": "中国",
        "status": "2025年11月8日起实施出口许可",
        "rule": (
            "达到参数门槛的高能量密度锂离子电池、关键设备、磷酸铁锂正极、"
            "石墨负极及相关技术进入出口许可管理；不是对全部电池的一刀切禁运。"
        ),
        "sourceTitle": "商务部 海关总署公告2025年第58号",
        "sourceUrl": (
            "https://www.mofcom.gov.cn/cms_files/filemanager/policySummary/"
            "viewcore_24600584ed4a4abf8f74d7385d935f3c.html"
        ),
        "sourceType": "商务部、海关总署",
        "modelFormula": (
            "项目延迟现金影响＝受控产品或设备相关收入×许可证导致的交付延迟"
            "与取消比例＋替代采购或本地化额外成本。"
        ),
        "boundary": "只有产品参数、技术和目的地落入清单且许可证影响交付时才进入公司情景。",
    },
    {
        "policyId": "eu_digital_battery_passport_2026",
        "jurisdiction": "欧盟",
        "status": "登记系统推进中，2027年2月起强制",
        "rule": (
            "欧盟数字产品护照登记系统计划于2026年运行，相关电动车、"
            "轻型交通及2kWh以上工业电池自2027年2月18日起配置电池护照。"
        ),
        "sourceTitle": "European Commission Digital Product Passport",
        "sourceUrl": (
            "https://single-market-economy.ec.europa.eu/single-market/"
            "digital-product-passport/batteries_en"
        ),
        "sourceType": "欧盟委员会",
        "modelFormula": (
            "合规成本＝一次性数据系统与供应链改造资本开支＋持续认证、"
            "审计和数据运营费用。"
        ),
        "boundary": "护照提升准入与追溯，不应按收入统一扣减；头部和小厂成本比例不同。",
    },
    {
        "policyId": "eu_industrial_accelerator_proposal_2026",
        "jurisdiction": "欧盟",
        "status": "欧盟委员会提案，尚未完成立法",
        "rule": (
            "提案拟对电池等战略行业的大型第三国外资附加就业、本地含量、"
            "技术与治理条件，并设置投资额和来源国全球产能份额门槛。"
        ),
        "sourceTitle": "Industrial Accelerator Act proposal",
        "sourceUrl": (
            "https://commission.europa.eu/news-and-media/news/"
            "commission-proposes-new-measures-boost-eu-industry-and-jobs-"
            "2026-03-04_en"
        ),
        "sourceType": "欧盟委员会",
        "modelFormula": (
            "提案情景影响＝新增本地化资本开支＋技术/治理约束造成的项目折价"
            "－获得本地市场与融资的价值。"
        ),
        "boundary": "尚未完成立法，只能作为政策压力测试，不能当作现行义务。",
    },
    {
        "policyId": "india_acc_battery_pli",
        "jurisdiction": "印度",
        "status": "执行中",
        "rule": (
            "先进化学电池生产激励计划目标50GWh，截至2026年2月已向四家"
            "受益企业分配40GWh，政策目标是形成本地制造和供应链。"
        ),
        "sourceTitle": "Production Linked Incentive Scheme for ACC Battery Storage",
        "sourceUrl": (
            "https://www.pib.gov.in/PressReleasePage.aspx?"
            "PRID=2225877&lang=1&reg=1"
        ),
        "sourceType": "印度政府新闻局",
        "modelFormula": (
            "项目价值＝本地客户与激励形成的税后现金流－本地化资本开支－"
            "爬坡成本－进口与本地含量约束成本。"
        ),
        "boundary": "计划容量不等于中国企业可获得份额，需核验获配主体、客户和本地资格。",
    },
    {
        "policyId": "brazil_storage_auction_2026",
        "jurisdiction": "巴西",
        "status": "首次电池储能拍卖规则推进中",
        "rule": (
            "巴西矿业和能源部发布首次电池储能拍卖指引，需求机会来自电网"
            "容量与灵活性，而不是传统新能源汽车补贴。"
        ),
        "sourceTitle": "Battery Energy Storage Auction Guidelines",
        "sourceUrl": (
            "https://www.gov.br/mme/pt-br/assuntos/noticias/"
            "mme-publica-diretrizes-para-leilao-inedito-de-armazenamento-"
            "de-energia-em-baterias-no-brasil"
        ),
        "sourceType": "巴西矿业和能源部",
        "modelFormula": (
            "可服务电芯需求＝中标功率×时长÷系统效率×企业供货份额；"
            "利润还需扣除项目融资、质保和本地交付成本。"
        ),
        "boundary": "拍卖规则和中标规模落实前只作为需求管线，不计确定订单。",
    },
]


COMPANY_EXPOSURES: list[dict[str, Any]] = [
    {
        "company": "鹏辉能源",
        "companyId": 661,
        "ticker": "300438.SZ",
        "reportedOverseasRevenuePct": 15.01,
        "reportedDomesticRevenuePct": 84.99,
        "revenueScope": "2025年集团分地区收入",
        "sourceRef": "鹏辉能源2025年报，第14页",
        "exposure": (
            "储能产品可销往美国、欧洲等市场，但公司未单独披露美国直供收入。"
            "相较龙头，出口退税和美国储能关税对利润率的边际敏感度更高，"
            "而海外本地制造缓冲仍有限。"
        ),
        "politicalRisk": "高：储能出口增长快、规模和议价能力弱于宁德时代。",
    },
    {
        "company": "宁德时代",
        "companyId": 254,
        "ticker": "300750.SZ",
        "reportedOverseasRevenuePct": 30.60,
        "reportedDomesticRevenuePct": 69.40,
        "revenueScope": "2025年集团分地区收入",
        "sourceRef": "宁德时代2025年报，第25页",
        "exposure": (
            "德国工厂已量产，匈牙利5GWh模组线于2026年5月启动，"
            "匈牙利电芯、与Stellantis的西班牙合资及印尼产业链继续推进。"
            "欧洲本地化降低整车贸易壁垒，但爬坡期固定成本和合规资本开支先于规模收益。"
        ),
        "politicalRisk": "中高：地域分散能力最强，但美国技术授权/PFE资格仍是条件变量。",
    },
    {
        "company": "比亚迪",
        "companyId": 414,
        "ticker": "002594.SZ",
        "reportedOverseasRevenuePct": 38.65,
        "reportedDomesticRevenuePct": 61.35,
        "revenueScope": "2025年集团收入，包含汽车、手机部件及组装等，不能视作电池出口占比",
        "sourceRef": "比亚迪2025年报，第29—30页",
        "exposure": (
            "欧盟反补贴税首先作用于中国生产整车；匈牙利本地整车制造可降低关税摩擦，"
            "但初期利用率、欧洲人工能源成本和本地供应链爬坡可能抵消部分税差。"
            "自产电池影响应由欧洲整车销量和单车带电量传导，而非直接对集团收入扣税。"
        ),
        "politicalRisk": "中高：海外增长贡献大，整车贸易和本地化执行同时决定电池利润。",
    },
    {
        "company": "国轩高科",
        "companyId": 662,
        "ticker": "002074.SZ",
        "reportedOverseasRevenuePct": 22.59,
        "reportedDomesticRevenuePct": 77.41,
        "revenueScope": "2025年集团分地区收入（含港澳台）",
        "sourceRef": "国轩高科2025年报，第20页",
        "exposure": (
            "泰国、越南已有产能，伊利诺伊项目仍在建设并形成大额在建工程，"
            "摩洛哥、斯洛伐克等布局面向欧美客户。美国项目是否满足PFE、"
            "有效控制和材料援助规则，直接决定本地化资产能否取得45X。"
        ),
        "politicalRisk": "很高：美国资产投入较大，补贴资格和政治审查对项目回报非线性。",
    },
    {
        "company": "中创新航",
        "companyId": 663,
        "ticker": "3931.HK",
        "reportedOverseasRevenuePct": 2.10,
        "reportedDomesticRevenuePct": 97.90,
        "revenueScope": "2025年按交付地点划分的集团收入",
        "sourceRef": "中创新航2025年报，第20页",
        "exposure": (
            "2025年海外收入基数很低，但葡萄牙和泰国法人/项目构成未来本地化期权。"
            "政策风险当前更多体现为新增资本开支和爬坡风险，而不是存量海外利润被直接冲击。"
        ),
        "politicalRisk": "中：存量直接暴露低，欧洲扩张成败决定未来风险上升速度。",
    },
    {
        "company": "亿纬锂能",
        "companyId": 664,
        "ticker": "300014.SZ",
        "reportedOverseasRevenuePct": 23.56,
        "reportedDomesticRevenuePct": 76.44,
        "revenueScope": "2025年集团分地区收入",
        "sourceRef": "亿纬锂能2025年报，第20页",
        "exposure": (
            "马来西亚基地已投产并继续扩储能，匈牙利大圆柱项目邻近宝马工厂，"
            "北美以客户合作/服务和储能市场为主。东南亚本地制造可缓冲中国出口政策，"
            "但美国最终市场关税和PFE仍可能沿客户订单传导。"
        ),
        "politicalRisk": "中高：海外收入可观，马来西亚提供缓冲，匈牙利爬坡推高资本需求。",
    },
    {
        "company": "瑞浦兰钧",
        "companyId": 665,
        "ticker": "0666.HK",
        "reportedOverseasRevenuePct": 5.87,
        "reportedDomesticRevenuePct": 94.13,
        "revenueScope": "2025年按直接签约客户所在地划分的集团收入",
        "sourceRef": "瑞浦兰钧2025年报，第127页",
        "exposure": (
            "印尼一期规划8GWh并在2025年爬坡，用于降低贸易壁垒；"
            "年报同时披露关税不确定性曾导致海外客户暂停电池部件订单。"
            "当前海外收入占比不高，但订单波动已证明贸易政策具有实际经营传导。"
        ),
        "politicalRisk": "中高：存量地域收入低，但储能出口扩张和较小资产负债表放大波动。",
    },
    {
        "company": "欣旺达",
        "companyId": 666,
        "ticker": "300207.SZ",
        "reportedOverseasRevenuePct": 38.64,
        "reportedDomesticRevenuePct": 61.36,
        "revenueScope": "2025年集团收入，境外收入主要为消费类电池",
        "sourceRef": "欣旺达2025年报，第14—15页",
        "exposure": (
            "越南消费电芯基地推进，泰国动力电池一期投产；集团海外占比较高，"
            "但不能把消费电池出口占比直接套到动力/储能模型。"
            "政策冲击需按消费、动力、储能和地区重新拆分。"
        ),
        "politicalRisk": "中高：集团海外高暴露，但电池业务结构错配使粗略比例尤其容易误判。",
    },
    {
        "company": "孚能科技",
        "companyId": 667,
        "ticker": "688567.SH",
        "reportedOverseasRevenuePct": 81.88,
        "reportedDomesticRevenuePct": 18.12,
        "revenueScope": "2025年主营电池业务分地区收入；占集团总收入约78.05%",
        "sourceRef": "孚能科技2025年报，第28页及第197页",
        "exposure": (
            "土耳其Siro 6GWh已完成爬坡并服务欧洲、中东和非洲，"
            "但中国出口退税下降和美国关税已被公司明确列为2025年毛利率压力。"
            "高海外占比与尚未稳定盈利叠加，使政策成本更难由利润缓冲。"
        ),
        "politicalRisk": "很高：海外收入占比最高、盈利脆弱，本地化缓冲与出口税负并存。",
    },
]


POLITICAL_OUTLOOK = [
    {
        "region": "中国",
        "currentSituation": (
            "政策组合已从单纯鼓励出口量，转向取消出口退税、恢复成熟电池消费税，"
            "同时对钠电和固态给予阶段性免税。"
        ),
        "baseCase": (
            "2026—2028年税制按公告执行，行业通过涨价、供应链抵扣和产品升级分担成本；"
            "低毛利、出口占比高且议价弱的企业先承压。"
        ),
        "upside": "先进化学体系免税延续或头部厂商成功向客户转嫁税负。",
        "downside": "价格竞争阻碍转嫁、抵扣链条不完整，现金税负接近机械上限。",
        "financialVariables": ["国内应税收入比例", "转嫁率", "已税投入抵扣率", "出口收入比例"],
    },
    {
        "region": "美国",
        "currentSituation": (
            "车辆端补贴退坡与制造端45X并存，但301关税、FEOC/PFE和有效控制规则"
            "把政策重点从普遍电动化补贴转向本地、安全、非中国控制的供应链。"
        ),
        "baseCase": (
            "中国直供美国的动力和储能份额继续受压；技术授权、合资和本地生产"
            "只有在所有权、材料和控制权合规后才可能获得政策收益。"
        ),
        "upside": "独立本地实体通过PFE审查，产量爬坡并兑现45X。",
        "downside": "PFE解释扩大到技术许可或关键材料，已投资项目无法取得抵免或客户退出。",
        "financialVariables": ["美国直供收入", "关税承担", "合资格本地产量", "PFE资格实现率"],
    },
    {
        "region": "欧盟",
        "currentSituation": (
            "欧洲不是简单排除中国供应商，而是同时使用整车贸易防御、追溯/碳足迹规则、"
            "尽职调查和本地电芯融资，推动“可审计的本地化”。"
        ),
        "baseCase": (
            "中国企业可凭欧洲工厂保留客户，但前两三年利用率和合规投入压低回报；"
            "无息贷款只缓解融资成本，不能替代产能爬坡。"
        ),
        "upside": "获得Battery Booster贷款并快速提高本地产能利用率。",
        "downside": "外资筛查、补贴资格或本地含量继续收紧，低利用率工厂形成现金拖累。",
        "financialVariables": ["欧洲本地产量", "利用率", "合规资本开支", "无息贷款", "整车销量"],
    },
    {
        "region": "印度、东南亚与中东非",
        "currentSituation": (
            "印度、东南亚和摩洛哥等地区正用本地制造激励、关税和开发性融资"
            "承接电池产业链，但终端需求、供应链完整度和项目融资成熟度差异很大。"
        ),
        "baseCase": (
            "中国企业优先通过马来西亚、泰国、印尼、摩洛哥等项目服务区域客户或"
            "作为对欧美出口缓冲；量产速度慢于规划产能。"
        ),
        "upside": "本地客户、开发性融资和出口通道同时兑现，利用率快速提高。",
        "downside": "本地需求不足、供应链依赖进口或政策提高本地含量，项目形成低利用率资产。",
        "financialVariables": ["项目投资", "当地销量", "利用率", "开发性融资", "本地化成本"],
    },
    {
        "region": "拉丁美洲",
        "currentSituation": (
            "电动车销量增速较高，巴西开始用储能拍卖建立电网需求；与此同时，"
            "整车关税和本地制造政策正在提高直接出口的不确定性。"
        ),
        "baseCase": (
            "储能和经济型电动车形成增量市场，但规模与利润依赖拍卖、中标、"
            "项目融资和本地渠道，不把高同比直接外推。"
        ),
        "upside": "巴西储能拍卖形成连续项目管线，区域EV渗透持续超预期。",
        "downside": "融资成本、汇率、关税和本地化要求延迟项目或压低回款。",
        "financialVariables": ["中标GWh", "项目融资", "汇率", "关税承担", "回款周期"],
    },
    {
        "region": "关键矿产与材料",
        "currentSituation": (
            "锂、钴、石墨等精炼和加工集中度继续上升，电池材料与锂矿资本开支"
            "在低价阶段下降，出口配额和许可已把地缘风险转为实际经营变量。"
        ),
        "baseCase": (
            "铁锂降低镍钴暴露但仍依赖锂和石墨；头部通过长协、回收和供应链布局"
            "缓冲波动，中小企业更易受到价格与交付冲击。"
        ),
        "upside": "材料供给扩张、回收料来源增加且贸易许可稳定，成本波动下降。",
        "downside": "上游投资不足与出口限制叠加，材料成本、库存和交付同时恶化。",
        "financialVariables": ["材料价格", "采购合同", "库存", "出口许可", "回收料来源"],
    },
]


def build(output: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": "lithium_battery.policy_scenarios.v1",
        "asOfDate": "2026-07-28",
        "policies": POLICIES,
        "companyExposures": COMPANY_EXPOSURES,
        "politicalOutlook": POLITICAL_OUTLOOK,
        "calculatorDefaults": {
            "taxPassThroughPct": 50.0,
            "upstreamTaxDeductiblePct": 50.0,
            "exportPassThroughPct": 50.0,
            "usTariffPct": 25.0,
            "usSupplierAbsorptionPct": 50.0,
            "euAlternativeBorrowingRatePct": 5.0,
            "usdCny": 7.15,
            "eurCny": 8.35,
            "us45xCellUsdPerKwh": 35.0,
            "us45xModuleUsdPerKwh": 10.0,
            "us45xEligibilityPct": 0.0,
            "us45xUtilizationPct": 0.0,
            "companySpecificSharesDefaultToZero": (
                "国内应税、出口退税清单内收入和美国直供收入均默认0；"
                "研究员必须按公司业务口径显式输入，披露海外收入只显示为上限锚。"
            ),
        },
        "unitSensitivities": {
            "chinaConsumptionTaxGrossPerRmb10bnEligibleRevenue": {
                "2026": 0.66666667,
                "2027": 2.66666667,
                "2028": 4.0,
                "unit": "亿元，未计转嫁和抵扣",
            },
            "chinaExportRebateLossPerRmb10bnEligibleExportRevenue": {
                "2026": 2.25,
                "2027": 9.0,
                "2028": 9.0,
                "unit": "亿元，未计转嫁",
            },
            "usTariffGrossPerRmb10bnDirectExportRevenue": {
                "allYears": 25.0,
                "unit": "亿元，未计进口商/供应商承担分配",
            },
            "euInterestSavingPerEur500mLoanAt5Pct": {
                "annualEurMillion": 25.0,
                "unit": "百万欧元/年，只有实际获批提款后成立",
            },
            "us45xGrossPer10GwhCellAndModuleAtFullEligibility": {
                "annualUsdMillion": 450.0,
                "unit": "百万美元/年，未计PFE、利用率和退坡",
            },
        },
        "modelBoundary": (
            "本底稿将已生效政策与研究情景分开。任何公司级结果都必须显示实际输入，"
            "不得以海外总收入自动替代出口退税清单收入或美国直接出口收入，"
            "不得把未获批的45X或欧盟无息贷款放进基准利润。"
        ),
    }
    payload["contentSha256"] = _sha(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build(args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "policies": len(payload["policies"]),
                "companies": len(payload["companyExposures"]),
                "contentSha256": payload["contentSha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
