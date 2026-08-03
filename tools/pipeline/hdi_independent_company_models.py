from __future__ import annotations

"""Build independent FY1-FY3 financial and valuation models for HDI leaders.

The model inputs intentionally exclude Wind ``west_*`` consensus fields and
broker earnings forecasts.  They use reported actuals, company disclosures and
explicit operating assumptions.  External consensus is collected only after
this export has been imported and frozen in ``financial.db``.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "cache" / "hdi_research" / "wind_actual_snapshot.json"
LEDGER = ROOT / "cache" / "hdi_research" / "financial_assumption_ledger.json"
EXPORT = ROOT / "cache" / "hdi_research" / "financial_model_profile_export.json"
AS_OF_DATE = "2026-07-24"
RUN_REF = "hdi_b_20260726"

COMPANIES: dict[str, dict[str, Any]] = {
    "002463.SZ": {
        "name": "沪电股份",
        "company_id": 326,
        "model_level": "Level 2：高阶产品量价与财务桥接结合",
        "sources": [
            "papers/HDI/沪电股份2025年报.pdf",
            "papers/HDI/沪电股份2026Q1.pdf",
            "papers/HDI/沪电H股招股书.pdf",
        ],
        "driver_summary": (
            "2025年收入189.45亿元、归母净利38.22亿元；2026Q1收入62.14亿元、"
            "归母净利12.42亿元。2025年数据通信PCB收入146.56亿元，22—30层与"
            "32层以上PCB的销售面积、单价均已形成连续披露；高阶产能扩张仍需用"
            "泰国认证、稼动率和高层板毛利兑现验证。"
        ),
        "forecasts": {
            2026: {
                "revenue": 270.0,
                "net_margin": 23.0,
                "ocf_conversion": 1.10,
                "capex": 50.0,
            },
            2027: {
                "revenue": 370.0,
                "net_margin": 24.0,
                "ocf_conversion": 1.15,
                "capex": 55.0,
            },
            2028: {
                "revenue": 480.0,
                "net_margin": 24.5,
                "ocf_conversion": 1.15,
                "capex": 45.0,
            },
        },
        "revenue_uncertainty": 0.12,
        "margin_uncertainty_pp": 2.0,
        "target_pe": (25.0, 32.0),
        "normalized_roe": 25.0,
        "long_growth": 7.0,
        "cost_of_equity": 12.5,
        "key_risk": (
            "模型要求32层以上板的面积、ASP和毛利率共同增长，并对泰国产线认证及"
            "稼动率保留折扣；若客户集中度上升但份额或定价转弱，收入高增不一定"
            "转化为同幅度利润和现金流。"
        ),
        "difference_causes": [
            "独立模型依据已披露的高层板面积和ASP放量，但没有把技术上限、在建产能或客户共同开发直接当作订单。",
            "外部预测对2027—2028年AI服务器机架、交换机和泰国产能释放更乐观，独立模型对远期净利率与产能兑现保留折扣。",
        ],
        "operating_analysis": (
            "沪电股份的核心优势是高层板量价已有可复算记录，而不是只有技术或规划。独立模型预计"
            "2026—2028年收入270/370/480亿元、归母净利润62.10/88.80/117.60亿元；"
            "资本开支约50/55/45亿元，2026年自由现金流近似值约18.31亿元，随后随稼动率"
            "提升扩大。真正需要验证的是32层以上销售面积、ASP、毛利和泰国产能是否同步兑现。"
        ),
        "valuation_analysis": (
            "核心估值采用2027年88.80亿元归母净利润和25—32倍市盈率，对应约2220—2842亿元"
            "市值。PB—ROE只作回报约束：可持续ROE 25%、长期增长7%、股权成本12.5%对应约"
            "3.27倍诊断PB，明显低于当前高增长阶段PB，说明价格已经计入较长的超额回报期。"
        ),
        "buy_point_analysis": (
            "股价接近核心估值下沿且32层以上面积、泰国认证、季度经营现金流至少两项继续改善时，"
            "估值与经营确认形成较好的组合；只有价格回落而高层板ASP或客户份额恶化，不构成买点。"
        ),
        "sell_point_analysis": (
            "若市值超过核心估值上沿而2027年盈利没有同步上修，或32层以上板面积增长但ASP、"
            "毛利、现金流转弱，应降低对长期高增长和高PB持续性的假设。"
        ),
        "future_view": "重点跟踪32层以上面积与ASP、泰国客户认证和稼动率、数据通信PCB毛利及经营现金流。",
        "positive_trigger": "32层以上板量价齐升、泰国批量认证兑现且经营现金流持续覆盖资本开支。",
        "risk_trigger": "高阶客户份额下降、ASP或毛利转弱，或泰国产能爬坡慢于资本开支投放。",
    },
    "002916.SZ": {
        "name": "深南电路",
        "company_id": 472,
        "model_level": "Level 2：分业务增长与财务桥接结合",
        "sources": [
            "papers/HDI/深南电路2025年报.pdf",
            "papers/HDI/深南电路2026Q1.pdf",
            "papers/HDI/深南电路A股招股书.pdf",
        ],
        "driver_summary": (
            "2025年收入236.47亿元、归母净利32.76亿元；2026Q1收入65.96亿元、"
            "归母净利8.50亿元。公司具有PCB、封装基板和电子装联三类业务，68层"
            "PCB已量产、120层仍属样品边界；南通、泰国和IC载板扩产需分别考虑"
            "认证、折旧和稼动率，不能把集团收入全部视为HDI。"
        ),
        "forecasts": {
            2026: {
                "revenue": 310.0,
                "net_margin": 16.5,
                "ocf_conversion": 1.35,
                "capex": 60.0,
            },
            2027: {
                "revenue": 410.0,
                "net_margin": 18.0,
                "ocf_conversion": 1.35,
                "capex": 50.0,
            },
            2028: {
                "revenue": 520.0,
                "net_margin": 19.0,
                "ocf_conversion": 1.30,
                "capex": 42.0,
            },
        },
        "revenue_uncertainty": 0.12,
        "margin_uncertainty_pp": 2.0,
        "target_pe": (30.0, 40.0),
        "normalized_roe": 25.0,
        "long_growth": 6.0,
        "cost_of_equity": 11.5,
        "key_risk": (
            "PCB、封装基板和装联业务的增长、利润率与资本强度不同；模型没有把"
            "120层样品、扩产规划或AI总需求直接计为量产收入。若载板亏损改善、"
            "泰国认证或高端PCB稼动率不及预期，利润率恢复将慢于收入。"
        ),
        "difference_causes": [
            "独立模型把PCB、封装基板和装联的利润率恢复合并为保守财务桥，没有把样品层数或规划产能视为已实现收入。",
            "最近两个季度卖方对AI PCB规格升级、800G/1.6T光模块和ABF载板改善的远期增量更乐观，因此2027—2028年预测上沿更高。",
        ],
        "operating_analysis": (
            "深南电路的优势是通信和数据中心PCB、封装基板与系统客户协同，但混合业务也会掩盖"
            "单一板类的盈利质量。独立模型预计2026—2028年收入310/410/520亿元、归母净利润"
            "51.15/73.80/98.80亿元；同期资本开支约60/50/42亿元，自由现金流近似值约"
            "9.05/49.63/86.44亿元。利润上沿取决于高端PCB结构升级和载板亏损收窄同时发生。"
        ),
        "valuation_analysis": (
            "核心估值采用2027年73.80亿元归母净利润和30—40倍市盈率，对应约2214—2952亿元"
            "市值。按可持续ROE 25%、长期增长6%、股权成本11.5%计算，诊断PB约3.45倍；当前"
            "高PB只有在PCB利润率、载板改善和现金回报同时兑现时才具有持续性。"
        ),
        "buy_point_analysis": (
            "股价进入核心估值区间，同时PCB分部利润、载板亏损、泰国认证和自由现金流中至少两项"
            "连续改善时，才形成经营与估值共同确认的买点；单看120层样品或扩产公告不足。"
        ),
        "sell_point_analysis": (
            "若估值超过核心区间上沿，而载板仍亏损、泰国或南通稼动率落后、经营现金流未随利润"
            "改善，应下调远期利润率和高估值持续期。"
        ),
        "future_view": "重点跟踪PCB分部高层板收入与毛利、载板亏损改善、泰国认证、资本开支和经营现金流。",
        "positive_trigger": "高端PCB产品结构改善、载板亏损收窄且新增产能稼动率提升，带动自由现金流扩大。",
        "risk_trigger": "扩产折旧先于收入、载板改善延后，或高端PCB订单和认证弱于当前市场预期。",
    },
    "300476.SZ": {
        "name": "胜宏科技",
        "company_id": 555,
        "model_level": "Level 2：业务驱动与财务桥接结合",
        "sources": [
            "papers/HDI/胜宏科技2025年报.pdf",
            "papers/HDI/胜宏科技2026Q1.pdf",
            "papers/HDI/胜宏科技H股.pdf",
        ],
        "driver_summary": (
            "2026Q1收入55.19亿元、归母净利12.88亿元；泰国A1已量产，"
            "A2计划2026Q3量产。A1设计产值约为2025年收入的26%，A2/A3"
            "各比A1高40%—100%，但AI产品仍受客户认证、良率和平台节奏约束。"
        ),
        "forecasts": {
            2026: {
                "revenue": 285.0,
                "net_margin": 23.5,
                "ocf_conversion": 0.95,
                "capex": 85.0,
            },
            2027: {
                "revenue": 430.0,
                "net_margin": 25.0,
                "ocf_conversion": 1.00,
                "capex": 90.0,
            },
            2028: {
                "revenue": 560.0,
                "net_margin": 24.5,
                "ocf_conversion": 1.05,
                "capex": 75.0,
            },
        },
        "revenue_uncertainty": 0.15,
        "margin_uncertainty_pp": 2.5,
        "target_pe": (22.0, 28.0),
        "normalized_roe": 28.0,
        "long_growth": 8.0,
        "cost_of_equity": 12.0,
        "key_risk": (
            "模型对A2/A3产能按期爬坡和AI客户认证较敏感；若下一代平台延期或"
            "供应份额分散，收入上沿和利润率上沿会同时下修。"
        ),
        "difference_causes": [
            "独立模型没有把A2/A3设计产值直接当作已获得订单，并对客户认证、良率和平台切换保留折扣。",
            "卖方预测对Rubin、ASIC和光模块PCB放量的兑现速度更乐观，因此2027—2028年收入与利润中枢更高。",
        ],
        "operating_analysis": (
            "胜宏科技的核心变量不是行业总量是否增长，而是泰国A2/A3能否按期完成认证并把高阶HDI、"
            "高多层和光模块PCB转成可重复量产收入。独立模型预计2026—2028年收入285/430/560亿元、"
            "归母净利润66.98/107.50/137.20亿元；扩产阶段资本开支约85/90/75亿元，经营现金流即使"
            "随利润改善，2026—2027年的自由现金流近似值仍为负，利润兑现和现金回收不能混为一谈。"
        ),
        "valuation_analysis": (
            "核心估值采用2027年107.50亿元归母净利润和22—28倍市盈率；PB—ROE只做回报强度复核。"
            "按可持续ROE 28%、长期增长8%、股权成本12%计算，诊断PB约5.00倍，低于当前约6.33倍，"
            "说明当前价格已要求较长的超额增长期，不能只因行业高增长就继续上调倍数。"
        ),
        "buy_point_analysis": (
            "只有当股价进入核心估值下沿附近，同时A2量产、重点平台认证和季度现金流至少两项得到"
            "验证时，风险收益比才明显改善；若只是价格下跌而认证或良率恶化，不构成经营型买点。"
        ),
        "sell_point_analysis": (
            "股价超过核心估值上沿但盈利预测没有同步上修，或A2/A3投产延后、客户份额下降、"
            "经营现金流持续落后净利润时，应降低对远期高增长的估值权重。"
        ),
        "future_view": "未来四个季度重点跟踪泰国A2量产、下一代AI平台认证、高端产品收入占比和经营现金流。",
        "positive_trigger": "A2按期量产并获得可核验客户订单，且高端产品毛利与现金转换同时改善。",
        "risk_trigger": "平台延期、认证失败、良率爬坡慢于计划，或新增资本开支继续抬升而现金流没有改善。",
    },
    "002938.SZ": {
        "name": "鹏鼎控股",
        "company_id": 556,
        "model_level": "Level 2：分业务增量与财务桥接结合",
        "sources": [
            "papers/HDI/鹏鼎控股2025年报.pdf",
            "papers/HDI/鹏鼎控股2026Q1.pdf",
        ],
        "driver_summary": (
            "2026Q1收入79.86亿元、归母净利4.63亿元；公司披露淮安IHDI/HLC"
            "产能预计2026年底翻倍，泰国一厂已试产，并计划在淮安分阶段投入"
            "80亿元和110亿元扩充高端PCB。消费电子基本盘仍决定短期收入基数。"
        ),
        "forecasts": {
            2026: {
                "revenue": 430.0,
                "net_margin": 9.5,
                "ocf_conversion": 1.60,
                "capex": 140.0,
            },
            2027: {
                "revenue": 500.0,
                "net_margin": 10.5,
                "ocf_conversion": 1.60,
                "capex": 120.0,
            },
            2028: {
                "revenue": 575.0,
                "net_margin": 11.0,
                "ocf_conversion": 1.55,
                "capex": 95.0,
            },
        },
        "revenue_uncertainty": 0.10,
        "margin_uncertainty_pp": 1.5,
        "target_pe": (20.0, 26.0),
        "normalized_roe": 12.5,
        "long_growth": 5.0,
        "cost_of_equity": 11.0,
        "key_risk": (
            "高端IHDI/HLC扩产金额大、折旧先于收入确认；若认证或稼动率慢于"
            "计划，收入可以增长但自由现金流和ROE仍可能下降。"
        ),
        "difference_causes": [
            "独立模型把淮安和泰国扩产先反映为资本开支与折旧压力，没有把规划产能一次性计入收入。",
            "最近两个季度卖方报告对AI服务器板、IHDI/HLC客户导入和消费电子复苏的速度更乐观。",
        ],
        "operating_analysis": (
            "鹏鼎控股的优势是消费电子基本盘、客户认证能力和大规模制造，但新一轮高端扩产会先消耗"
            "现金。独立模型预计2026—2028年收入430/500/575亿元、归母净利润40.85/52.50/63.25"
            "亿元；同期资本开支140/120/95亿元，自由现金流近似值仍为负，说明盈利增长必须和"
            "IHDI/HLC稼动率、折旧吸收及客户结构改善一起验证。"
        ),
        "valuation_analysis": (
            "核心估值使用2027年52.50亿元归母净利润和20—26倍市盈率。按可持续ROE 12.5%、"
            "长期增长5%、股权成本11%计算，诊断PB约1.25倍，显著低于当前约6.34倍；PB—ROE对"
            "转型期成长公司的解释力有限，但差距提示当前价格已经计入远高于稳态的回报与增长。"
        ),
        "buy_point_analysis": (
            "价格需要回到核心估值区间，同时淮安IHDI/HLC稼动率、泰国量产和自由现金流至少出现"
            "两项改善，才构成可验证的买点；单靠扩产公告不足以支持高估值。"
        ),
        "sell_point_analysis": (
            "若市场仍按高成长定价，但高端业务占比、利润率和现金流连续两个季度未改善，或资本开支"
            "继续上修，应把估值从成长溢价转回制造业现金回报约束。"
        ),
        "future_view": "重点跟踪淮安高端产能利用率、泰国客户认证、AI服务器收入占比及资本开支峰值。",
        "positive_trigger": "高端产能利用率上升、净利率向10%以上恢复且自由现金流由负转正。",
        "risk_trigger": "消费电子需求走弱叠加AI产能爬坡延迟，导致折旧、资本开支和低稼动率同时压制ROE。",
    },
    "603228.SH": {
        "name": "景旺电子",
        "company_id": 558,
        "model_level": "Level 2：产能节点与财务桥接结合",
        "sources": [
            "papers/HDI/景旺电子2025年报.pdf",
            "papers/HDI/景旺电子2026Q1.pdf",
        ],
        "driver_summary": (
            "2026Q1收入38.92亿元、归母净利2.33亿元，收入同比增16.41%但"
            "利润同比降28.37%；珠海规划年产60万平方米HDI（含SLP）和120万"
            "平方米HLC，部分产线已投产，泰国基地计划2026年投产。"
        ),
        "forecasts": {
            2026: {
                "revenue": 180.0,
                "net_margin": 7.3,
                "ocf_conversion": 1.40,
                "capex": 40.0,
            },
            2027: {
                "revenue": 220.0,
                "net_margin": 8.5,
                "ocf_conversion": 1.50,
                "capex": 35.0,
            },
            2028: {
                "revenue": 270.0,
                "net_margin": 9.5,
                "ocf_conversion": 1.50,
                "capex": 30.0,
            },
        },
        "revenue_uncertainty": 0.12,
        "margin_uncertainty_pp": 1.5,
        "target_pe": (18.0, 24.0),
        "normalized_roe": 14.0,
        "long_growth": 5.0,
        "cost_of_equity": 11.0,
        "key_risk": (
            "2026Q1已显示扩产期费用和产品结构可能压低利润；模型要求珠海、"
            "泰国产能在2027年后提高稼动率，否则利润恢复会明显落后收入增长。"
        ),
        "difference_causes": [
            "独立模型依据2026Q1利润同比下降的现实，对扩产初期净利率恢复更谨慎。",
            "卖方报告更强调AI算力和高端制造增量，对珠海、泰国产能爬坡速度及利润率弹性假设更高。",
        ],
        "operating_analysis": (
            "景旺电子的收入增长已经出现，但2026Q1归母净利润下降说明扩产折旧、费用与产品结构仍在"
            "压制盈利。独立模型预计2026—2028年收入180/220/270亿元、归母净利润13.14/18.70/"
            "25.65亿元；资本开支40/35/30亿元，只有珠海和泰国产能利用率提高，收入增长才会转化为"
            "利润率与自由现金流改善。"
        ),
        "valuation_analysis": (
            "核心估值以2027年18.70亿元归母净利润和18—24倍市盈率为主。按可持续ROE 14%、"
            "长期增长5%、股权成本11%计算，诊断PB约1.50倍，低于当前约5.76倍；这表明当前估值"
            "依赖利润率较快修复，不能用收入增长替代回报率验证。"
        ),
        "buy_point_analysis": (
            "股价进入核心估值区间且季度净利率、珠海/泰国稼动率、自由现金流中至少两项连续改善，"
            "才具备更好的赔率；在利润仍落后收入时不宜只根据订单或产能判断低估。"
        ),
        "sell_point_analysis": (
            "若股价继续反映高增长而净利率修复低于模型、泰国投产延后或资本开支重新上行，应下调"
            "盈利中枢和估值倍数，而不是等待收入增长自动解决问题。"
        ),
        "future_view": "重点观察收入增速与利润增速能否重新同向、珠海/泰国产能利用率及高端产品毛利。",
        "positive_trigger": "净利率向8.5%以上恢复、扩产项目利用率提升并带动自由现金流改善。",
        "risk_trigger": "收入增长但利润继续下降，或泰国产能爬坡不及预期、折旧和费用持续侵蚀回报率。",
    },
    "603459.SH": {
        "name": "红板科技",
        "company_id": 633,
        "model_level": "Level 3：财务桥接，公开前瞻经营数据有限",
        "sources": [
            (
                "papers/HDI/2025-10-21_上交所_红板科技_第二轮审核问询回复_"
                "HDI市场与份额.pdf"
            ),
            "https://www.sse.com.cn/disclosure/announcement/listing/ipo/c/c_20260407_10814322.shtml",
        ],
        "driver_summary": (
            "2024年HDI收入15.18亿元、在中国大陆HDI市场份额约2.1%；"
            "2025年Wind财务显示收入36.77亿元、归母净利5.40亿元。公司2026年"
            "4月上市，公开资料尚不足以把新增订单和产能拆成客户级预测。"
        ),
        "forecasts": {
            2026: {
                "revenue": 45.0,
                "net_margin": 14.0,
                "ocf_conversion": 1.30,
                "capex": 12.0,
            },
            2027: {
                "revenue": 55.0,
                "net_margin": 14.5,
                "ocf_conversion": 1.25,
                "capex": 12.0,
            },
            2028: {
                "revenue": 65.0,
                "net_margin": 14.5,
                "ocf_conversion": 1.20,
                "capex": 10.0,
            },
        },
        "revenue_uncertainty": 0.18,
        "margin_uncertainty_pp": 2.0,
        "target_pe": (22.0, 28.0),
        "normalized_roe": 20.0,
        "long_growth": 6.0,
        "cost_of_equity": 12.0,
        "key_risk": (
            "上市后可比历史短、当前估值很高，且HDI阶数、客户认证和新增产能"
            "的公开拆分不足；因此只做宽区间财务桥，不把份额直接外推为订单。"
        ),
        "difference_causes": [
            "公司上市时间短，公开资料尚不足以形成稳定的一致预期样本，当前只能与市场价格和经营阈值对账。",
            "独立模型没有把中国大陆产地口径2.1%的份额直接外推为全球订单，也没有假设客户认证自动成功。",
        ],
        "operating_analysis": (
            "红板科技2024年HDI收入15.18亿元，2025年公司整体收入36.77亿元、归母净利润5.40亿元，"
            "但上市后历史短，产品阶数、客户和新增产能披露仍不足。独立模型只做宽区间桥接：预计"
            "2026—2028年收入45/55/65亿元、归母净利润6.30/7.98/9.43亿元；结论应由后续年报和"
            "订单披露校准，不能把市场份额机械外推。"
        ),
        "valuation_analysis": (
            "核心估值采用2027年7.98亿元归母净利润和22—28倍市盈率。按可持续ROE 20%、长期增长"
            "6%、股权成本12%计算，诊断PB约2.33倍，显著低于当前约15.55倍；即使PB—ROE对新股"
            "成长阶段存在低估无形资产的问题，当前估值仍要求非常强的订单和盈利兑现。"
        ),
        "buy_point_analysis": (
            "只有价格显著回到模型区间，并且新客户、产品阶数、产能利用率和现金流出现可核验改善，"
            "才适合重新评估风险收益；上市初期波动或题材热度不能替代基本面买点。"
        ),
        "sell_point_analysis": (
            "若估值持续远高于模型区间，而后续财报没有显示收入、利润和现金流同步增长，或客户与"
            "高阶产品披露仍不足，应优先控制估值回落风险。"
        ),
        "future_view": "未来需用上市后连续财报验证客户结构、高阶HDI收入、产能利用率和现金转换。",
        "positive_trigger": "新增高阶HDI客户和订单获得公司披露，利润增长与经营现金流同步兑现。",
        "risk_trigger": "新股高估值维持但订单、产品结构或现金流证据没有补齐，或利润率明显低于模型。",
    },
}

SCENARIO_ASSUMPTIONS: dict[str, dict[str, dict[str, Any]]] = {
    "002463.SZ": {
        "downside": {
            "label": "下行情景",
            "revenue_change": -0.12,
            "margin_change_pp": -2.0,
            "ocf_conversion_change": -0.15,
            "capex_multiplier": 0.95,
            "condition": "高阶客户份额或32层以上需求弱于基准，泰国认证和稼动率延后；在建项目使资本开支只能小幅收缩。",
        },
        "base": {
            "label": "基准情景",
            "revenue_change": 0.0,
            "margin_change_pp": 0.0,
            "ocf_conversion_change": 0.0,
            "capex_multiplier": 1.0,
            "condition": "32层以上量价延续增长，泰国产能按计划认证爬坡，但不把规划产能和客户共同开发直接视为订单。",
        },
        "upside": {
            "label": "上行情景",
            "revenue_change": 0.12,
            "margin_change_pp": 2.0,
            "ocf_conversion_change": 0.10,
            "capex_multiplier": 1.08,
            "condition": "AI服务器机架与交换机升级快于基准，32层以上量价和泰国量产同时兑现并触发追加投资。",
        },
    },
    "002916.SZ": {
        "downside": {
            "label": "下行情景",
            "revenue_change": -0.12,
            "margin_change_pp": -2.0,
            "ocf_conversion_change": -0.15,
            "capex_multiplier": 0.95,
            "condition": "高端PCB、泰国认证或载板改善慢于基准，新增折旧先于收入，已投项目使资本开支保持高位。",
        },
        "base": {
            "label": "基准情景",
            "revenue_change": 0.0,
            "margin_change_pp": 0.0,
            "ocf_conversion_change": 0.0,
            "capex_multiplier": 1.0,
            "condition": "AI PCB结构升级、载板改善和新增产能按阶段兑现，不把样品层数或规划产能直接计入量产收入。",
        },
        "upside": {
            "label": "上行情景",
            "revenue_change": 0.12,
            "margin_change_pp": 2.0,
            "ocf_conversion_change": 0.10,
            "capex_multiplier": 1.08,
            "condition": "高端PCB客户需求、泰国认证和载板利润改善同时快于基准，产品组合与现金转换同步提升。",
        },
    },
    "300476.SZ": {
        "downside": {
            "label": "下行情景",
            "revenue_change": -0.15,
            "margin_change_pp": -2.5,
            "ocf_conversion_change": -0.15,
            "capex_multiplier": 0.95,
            "condition": "泰国A2/A3爬坡或下一代平台认证延后，高端份额低于基准；已启动项目使资本开支只小幅收缩。",
        },
        "base": {
            "label": "基准情景",
            "revenue_change": 0.0,
            "margin_change_pp": 0.0,
            "ocf_conversion_change": 0.0,
            "capex_multiplier": 1.0,
            "condition": "A2按计划量产、A3按披露节奏推进，客户认证与良率逐步兑现，但不把设计产值直接视为订单。",
        },
        "upside": {
            "label": "上行情景",
            "revenue_change": 0.15,
            "margin_change_pp": 2.5,
            "ocf_conversion_change": 0.10,
            "capex_multiplier": 1.10,
            "condition": "AI平台、ASIC和光模块PCB需求同时兑现，A2/A3认证与良率快于基准，并追加扩产。",
        },
    },
    "002938.SZ": {
        "downside": {
            "label": "下行情景",
            "revenue_change": -0.10,
            "margin_change_pp": -1.5,
            "ocf_conversion_change": -0.20,
            "capex_multiplier": 0.95,
            "condition": "IHDI/HLC认证和稼动率爬坡慢于计划，消费电子复苏偏弱；大额在建项目使现金支出仍保持高位。",
        },
        "base": {
            "label": "基准情景",
            "revenue_change": 0.0,
            "margin_change_pp": 0.0,
            "ocf_conversion_change": 0.0,
            "capex_multiplier": 1.0,
            "condition": "淮安高端产能和泰国一厂按计划导入，AI业务提升但消费电子仍是主要经营基盘。",
        },
        "upside": {
            "label": "上行情景",
            "revenue_change": 0.10,
            "margin_change_pp": 1.5,
            "ocf_conversion_change": 0.10,
            "capex_multiplier": 1.08,
            "condition": "IHDI/HLC客户导入和稼动率快于基准，高端产品改善组合并带动现金转换，同时追加配套投资。",
        },
    },
    "603228.SH": {
        "downside": {
            "label": "下行情景",
            "revenue_change": -0.12,
            "margin_change_pp": -1.5,
            "ocf_conversion_change": -0.15,
            "capex_multiplier": 0.90,
            "condition": "珠海HDI/HLC和泰国项目爬坡延后，汽车与AI需求未能抵消折旧和低稼动率。",
        },
        "base": {
            "label": "基准情景",
            "revenue_change": 0.0,
            "margin_change_pp": 0.0,
            "ocf_conversion_change": 0.0,
            "capex_multiplier": 1.0,
            "condition": "珠海与泰国产能逐步释放，AI、汽车和传统业务形成相对均衡的收入组合。",
        },
        "upside": {
            "label": "上行情景",
            "revenue_change": 0.12,
            "margin_change_pp": 1.5,
            "ocf_conversion_change": 0.10,
            "capex_multiplier": 1.08,
            "condition": "AI服务器和汽车高阶板放量快于基准，新产线良率、稼动率和现金回收同步改善。",
        },
    },
    "603459.SH": {
        "downside": {
            "label": "下行情景",
            "revenue_change": -0.18,
            "margin_change_pp": -2.0,
            "ocf_conversion_change": -0.20,
            "capex_multiplier": 0.90,
            "condition": "上市后新增客户和高阶HDI订单低于预期，产能利用率下降；项目缩减只能部分降低资本开支。",
        },
        "base": {
            "label": "基准情景",
            "revenue_change": 0.0,
            "margin_change_pp": 0.0,
            "ocf_conversion_change": 0.0,
            "capex_multiplier": 1.0,
            "condition": "现有客户与产品结构平稳扩张，不把大陆产地份额机械外推为公司订单。",
        },
        "upside": {
            "label": "上行情景",
            "revenue_change": 0.18,
            "margin_change_pp": 2.0,
            "ocf_conversion_change": 0.10,
            "capex_multiplier": 1.10,
            "condition": "高阶HDI客户、订单和产品阶数获得持续验证，较小收入基数带来更高弹性并触发追加投资。",
        },
    },
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_snapshot() -> dict[str, Any]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _actual(snapshot: dict[str, Any], ticker: str, year: int, field: str) -> float:
    raw = snapshot["wind"]["annual"][str(year)][ticker][field]
    if raw is None:
        raise ValueError(f"{ticker} {year} {field} is empty")
    return float(raw)


def _model_rows(
    snapshot: dict[str, Any],
    ticker: str,
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    revenue_2025 = _actual(snapshot, ticker, 2025, "OPER_REV") / 1e8
    profit_2025 = _actual(snapshot, ticker, 2025, "NP_BELONGTO_PARCOMSH") / 1e8
    ocf_2025 = _actual(snapshot, ticker, 2025, "NET_CASH_FLOWS_OPER_ACT") / 1e8
    capex_2025 = _actual(snapshot, ticker, 2025, "CASH_PAY_ACQ_CONST_FIOLTA") / 1e8
    source_ref = "; ".join(spec["sources"])
    inputs: list[dict[str, Any]] = [
        {
            "input_name": "2025年营业收入",
            "value_num": revenue_2025,
            "unit": "亿元人民币",
            "period_or_as_of_date": "2025",
            "source_ref": "Wind WSS.oper_rev，2025年报期末口径",
            "input_type": "direct_fact",
            "formula_or_method": "Wind年报口径，单位由元换算为亿元",
        },
        {
            "input_name": "2025年归母净利润",
            "value_num": profit_2025,
            "unit": "亿元人民币",
            "period_or_as_of_date": "2025",
            "source_ref": "Wind WSS.np_belongto_parcomsh，2025年报期末口径",
            "input_type": "direct_fact",
            "formula_or_method": "Wind年报口径，单位由元换算为亿元",
        },
        {
            "input_name": "2025年经营现金流",
            "value_num": ocf_2025,
            "unit": "亿元人民币",
            "period_or_as_of_date": "2025",
            "source_ref": "Wind WSS.net_cash_flows_oper_act，2025年报期末口径",
            "input_type": "direct_fact",
            "formula_or_method": "Wind年报口径，单位由元换算为亿元",
        },
        {
            "input_name": "2025年资本开支现金支出",
            "value_num": capex_2025,
            "unit": "亿元人民币",
            "period_or_as_of_date": "2025",
            "source_ref": "Wind WSS.cash_pay_acq_const_fiolta，2025年报期末口径",
            "input_type": "direct_fact",
            "formula_or_method": "购建固定资产、无形资产和其他长期资产支付的现金",
        },
        {
            "input_name": "经营与产能证据",
            "value_text": spec["driver_summary"],
            "unit": "文本",
            "period_or_as_of_date": AS_OF_DATE,
            "source_ref": source_ref,
            "input_type": "derived_fact",
            "formula_or_method": (
                "仅使用公司披露的实际经营、投产和技术信息设定情景，"
                "不读取一致预期数值"
            ),
            "limitation_note": spec["key_risk"],
        },
    ]
    outputs: list[dict[str, Any]] = []
    previous_revenue = revenue_2025
    uncertainty = float(spec["revenue_uncertainty"])
    margin_uncertainty = float(spec["margin_uncertainty_pp"])
    for year, forecast in spec["forecasts"].items():
        revenue = float(forecast["revenue"])
        margin = float(forecast["net_margin"])
        profit = revenue * margin / 100.0
        conversion = float(forecast["ocf_conversion"])
        capex = float(forecast["capex"])
        ocf = profit * conversion
        fcf = ocf - capex
        revenue_growth = revenue / previous_revenue - 1.0
        revenue_low = revenue * (1.0 - uncertainty)
        revenue_high = revenue * (1.0 + uncertainty)
        profit_low = revenue_low * (margin - margin_uncertainty) / 100.0
        profit_high = revenue_high * (margin + margin_uncertainty) / 100.0
        for input_name, value, unit, method in (
            (
                f"{year}年营业收入假设",
                revenue,
                "亿元人民币",
                f"上年收入×(1+经营增长)，对应同比{revenue_growth:.1%}",
            ),
            (
                f"{year}年净利率假设",
                margin,
                "%",
                "产品组合、稼动率、折旧与费用率的综合假设",
            ),
            (
                f"{year}年经营现金转换率假设",
                conversion,
                "倍",
                "经营现金流/归母净利润",
            ),
            (
                f"{year}年资本开支假设",
                capex,
                "亿元人民币",
                "结合在建项目和扩产阶段设置的研究情景",
            ),
        ):
            inputs.append(
                {
                    "input_name": input_name,
                    "value_num": value,
                    "unit": unit,
                    "period_or_as_of_date": str(year),
                    "source_ref": source_ref,
                    "input_type": "expert_assumption",
                    "formula_or_method": method,
                    "sensitivity_note": spec["key_risk"],
                }
            )
        outputs.extend(
            [
                {
                    "output_name": "营业收入",
                    "value_num": revenue,
                    "range_low": revenue_low,
                    "range_high": revenue_high,
                    "unit": "亿元人民币",
                    "period_or_as_of_date": str(year),
                    "formula": "营业收入＝上年收入×（1＋经营增长率）",
                    "substitution": (
                        f"{previous_revenue:.2f}×（1＋{revenue_growth:.1%}）"
                        f"＝{revenue:.2f}"
                    ),
                    "dependency_group": "经营增长与产能爬坡",
                    "conclusion": spec["driver_summary"],
                },
                {
                    "output_name": "归母净利润",
                    "value_num": profit,
                    "range_low": profit_low,
                    "range_high": profit_high,
                    "unit": "亿元人民币",
                    "period_or_as_of_date": str(year),
                    "formula": "归母净利润＝营业收入×净利率",
                    "substitution": f"{revenue:.2f}×{margin:.2f}%＝{profit:.2f}",
                    "dependency_group": "收入、产品组合与利润率",
                    "conclusion": spec["key_risk"],
                },
                {
                    "output_name": "经营现金流",
                    "value_num": ocf,
                    "unit": "亿元人民币",
                    "period_or_as_of_date": str(year),
                    "formula": "经营现金流＝归母净利润×现金转换率",
                    "substitution": f"{profit:.2f}×{conversion:.2f}＝{ocf:.2f}",
                    "dependency_group": "利润兑现与营运资本",
                    "conclusion": "现金转换率是研究假设，不等同于公司指引。",
                },
                {
                    "output_name": "自由现金流近似值",
                    "value_num": fcf,
                    "unit": "亿元人民币",
                    "period_or_as_of_date": str(year),
                    "formula": "自由现金流近似值＝经营现金流－资本开支现金支出",
                    "substitution": f"{ocf:.2f}－{capex:.2f}＝{fcf:.2f}",
                    "dependency_group": "经营现金流与扩产",
                    "conclusion": (
                        "该值用于比较扩产消耗，不替代含营运资本、租赁和并购调整的"
                        "完整FCFF。"
                    ),
                },
                {
                    "output_name": "资本开支",
                    "value_num": capex,
                    "unit": "亿元人民币",
                    "period_or_as_of_date": str(year),
                    "formula": "资本开支＝本情景购建长期资产现金支出假设",
                    "substitution": f"{capex:.2f}亿元",
                    "dependency_group": "扩产项目与建设节奏",
                    "conclusion": "资本开支是研究情景，不等同于公司正式预算。",
                },
            ]
        )
        previous_revenue = revenue
    return inputs, outputs


def _scenario_model_rows(
    ticker: str,
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build explicit operating states instead of treating a range as a scenario."""
    source_ref = "; ".join(spec["sources"])
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for scenario_name, scenario in SCENARIO_ASSUMPTIONS[ticker].items():
        label = str(scenario["label"])
        inputs.append(
            {
                "input_name": f"{label}经营条件",
                "value_text": str(scenario["condition"]),
                "unit": "文本",
                "period_or_as_of_date": "2026—2028",
                "source_ref": source_ref,
                "input_type": "expert_assumption",
                "formula_or_method": (
                    f"相对基准收入{float(scenario['revenue_change']):+.0%}、"
                    f"净利率{float(scenario['margin_change_pp']):+.1f}个百分点、"
                    f"现金转换率{float(scenario['ocf_conversion_change']):+.2f}倍、"
                    f"资本开支×{float(scenario['capex_multiplier']):.2f}"
                ),
                "sensitivity_note": spec["key_risk"],
            }
        )
        for year, base in spec["forecasts"].items():
            revenue = float(base["revenue"]) * (
                1.0 + float(scenario["revenue_change"])
            )
            margin = max(
                0.0,
                float(base["net_margin"]) + float(scenario["margin_change_pp"]),
            )
            conversion = max(
                0.0,
                float(base["ocf_conversion"])
                + float(scenario["ocf_conversion_change"]),
            )
            capex = float(base["capex"]) * float(scenario["capex_multiplier"])
            profit = revenue * margin / 100.0
            ocf = profit * conversion
            fcf = ocf - capex
            row = {
                "scenario_name": scenario_name,
                "scenario_label": label,
                "condition": str(scenario["condition"]),
                "year": int(year),
                "revenue": revenue,
                "net_income": profit,
                "operating_cash_flow": ocf,
                "capex": capex,
                "free_cash_flow": fcf,
            }
            observations.append(row)
            if scenario_name == "base":
                continue
            output_specs = (
                (
                    "营业收入",
                    revenue,
                    "营业收入＝基准收入×（1＋情景收入调整）",
                    f"{float(base['revenue']):.2f}×"
                    f"（1{float(scenario['revenue_change']):+.0%}）＝{revenue:.2f}",
                ),
                (
                    "归母净利润",
                    profit,
                    "归母净利润＝情景收入×情景净利率",
                    f"{revenue:.2f}×{margin:.2f}%＝{profit:.2f}",
                ),
                (
                    "经营现金流",
                    ocf,
                    "经营现金流＝情景归母净利润×情景现金转换率",
                    f"{profit:.2f}×{conversion:.2f}＝{ocf:.2f}",
                ),
                (
                    "资本开支",
                    capex,
                    "资本开支＝基准资本开支×情景扩产倍数",
                    f"{float(base['capex']):.2f}×"
                    f"{float(scenario['capex_multiplier']):.2f}＝{capex:.2f}",
                ),
                (
                    "自由现金流近似值",
                    fcf,
                    "自由现金流近似值＝情景经营现金流－情景资本开支",
                    f"{ocf:.2f}－{capex:.2f}＝{fcf:.2f}",
                ),
            )
            for output_name, value, formula, substitution in output_specs:
                outputs.append(
                    {
                        "output_name": f"{output_name}（{label}）",
                        "value_num": value,
                        "unit": "亿元人民币",
                        "period_or_as_of_date": str(year),
                        "formula": formula,
                        "substitution": substitution,
                        "dependency_group": f"{label}：收入、利润率、现金转换与扩产",
                        "conclusion": str(scenario["condition"]),
                    }
                )
    return inputs, outputs, observations


def _valuation_model(
    snapshot: dict[str, Any],
    ticker: str,
    spec: dict[str, Any],
    scenario_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    current = snapshot["wind"]["current"][ticker]
    price = float(current["CLOSE"])
    market_cap = float(current["MKT_CAP_ARD"]) / 1e8
    share_count = market_cap / price
    pe_low, pe_high = (float(value) for value in spec["target_pe"])
    pe_by_scenario = {
        "downside": pe_low,
        "base": (pe_low + pe_high) / 2.0,
        "upside": pe_high,
    }
    fy2_scenarios = {
        str(row["scenario_name"]): row
        for row in scenario_rows
        if int(row["year"]) == 2027
    }
    scenario_results: list[dict[str, Any]] = []
    for scenario_name in ("downside", "base", "upside"):
        row = fy2_scenarios[scenario_name]
        target_pe = pe_by_scenario[scenario_name]
        target_value = float(row["net_income"]) * target_pe
        scenario_results.append(
            {
                "scenario_name": scenario_name,
                "scenario_label": row["scenario_label"],
                "condition": row["condition"],
                "revenue": float(row["revenue"]),
                "net_income": float(row["net_income"]),
                "operating_cash_flow": float(row["operating_cash_flow"]),
                "capex": float(row["capex"]),
                "free_cash_flow": float(row["free_cash_flow"]),
                "target_pe": target_pe,
                "target_market_cap": target_value,
                "target_price": target_value / share_count,
            }
        )
    downside, base_case, upside = scenario_results
    source_ref = "; ".join(spec["sources"])
    return {
        "run_key": f"{RUN_REF}.{ticker}.pe_valuation.v3",
        "skill_name": "company_valuation_modeling",
        "model_name": "FY2三情景归母净利润×条件化市盈率",
        "model_role": "core",
        "forecast_start": "2026-01-01",
        "forecast_end": "2028-12-31",
        "valuation_date": AS_OF_DATE,
        "assumptions": {
            "valuation_role": "core",
            "no_consensus_input": True,
            "target_pe_range": [pe_low, pe_high],
            "scenario_results": scenario_results,
            "company_detail_summary": {
                "conclusion": (
                    f"2027年下行、基准和上行情景归母净利润分别为"
                    f"{downside['net_income']:.2f}/{base_case['net_income']:.2f}/"
                    f"{upside['net_income']:.2f}亿元；按{downside['target_pe']:.0f}/"
                    f"{base_case['target_pe']:.0f}/{upside['target_pe']:.0f}倍条件化"
                    f"市盈率，对应总市值约{downside['target_market_cap']:.2f}/"
                    f"{base_case['target_market_cap']:.2f}/"
                    f"{upside['target_market_cap']:.2f}亿元。估值日收盘价"
                    f"{price:.2f}元，任何价格判断都必须与情景经营条件同时验证。"
                ),
                "scenario_results": scenario_results,
                "difference_causes": spec["difference_causes"],
                "operating_analysis": spec["operating_analysis"],
                "valuation_analysis": spec["valuation_analysis"],
                "buy_point_analysis": spec["buy_point_analysis"],
                "sell_point_analysis": spec["sell_point_analysis"],
                "future_view": spec["future_view"],
                "positive_trigger": spec["positive_trigger"],
                "risk_trigger": spec["risk_trigger"],
            },
        },
        "limitations": (
            "收入、净利率、现金转换、资本开支和目标市盈率按可证伪经营状态联动；"
            "三情景不是概率预测，也不与其他估值方法机械平均。"
        ),
        "finalization": "independent",
        "inputs": [
            *[
                {
                    "input_name": f"2027年{row['scenario_label']}归母净利润",
                    "value_num": row["net_income"],
                    "unit": "亿元人民币",
                    "period_or_as_of_date": "2027",
                    "source_ref": f"{RUN_REF}.{ticker}.financial_bridge.v3",
                    "input_type": "derived_fact",
                    "formula_or_method": (
                        f"{row['revenue']:.2f}亿元×情景净利率；"
                        f"经营条件：{row['condition']}"
                    ),
                }
                for row in scenario_results
            ],
            *[
                {
                    "input_name": f"{row['scenario_label']}目标市盈率",
                    "value_num": row["target_pe"],
                    "unit": "倍",
                    "period_or_as_of_date": "2027",
                    "source_ref": source_ref,
                    "input_type": "expert_assumption",
                    "formula_or_method": (
                        "按增长、ROE、客户集中、产能兑现和现金流风险条件化取值"
                    ),
                    "limitation_note": spec["key_risk"],
                }
                for row in scenario_results
            ],
            {
                "input_name": "估算总股本",
                "value_num": share_count,
                "unit": "亿股",
                "period_or_as_of_date": AS_OF_DATE,
                "source_ref": "Wind WSS.mkt_cap_ard与close",
                "input_type": "derived_fact",
                "formula_or_method": "总股本≈总市值/收盘价",
            },
        ],
        "outputs": [
            output
            for row in scenario_results
            for output in (
                {
                    "output_name": f"{row['scenario_label']}目标市值",
                    "value_num": row["target_market_cap"],
                    "unit": "亿元人民币",
                    "period_or_as_of_date": "2027",
                    "formula": "目标市值＝情景归母净利润×条件化目标市盈率",
                    "substitution": (
                        f"{row['net_income']:.2f}×{row['target_pe']:.2f}"
                        f"＝{row['target_market_cap']:.2f}"
                    ),
                    "dependency_group": "情景利润与目标市盈率",
                    "conclusion": str(row["condition"]),
                },
                {
                    "output_name": f"{row['scenario_label']}对应股价",
                    "value_num": row["target_price"],
                    "unit": "元/股",
                    "period_or_as_of_date": "2027",
                    "formula": "情景对应股价＝情景目标市值÷估算总股本",
                    "substitution": (
                        f"{row['target_market_cap']:.2f}÷{share_count:.4f}"
                        f"＝{row['target_price']:.2f}"
                    ),
                    "dependency_group": "情景目标市值与股本",
                    "conclusion": (
                        f"估值日收盘价{price:.2f}元；必须与情景经营条件共同使用。"
                    ),
                },
            )
        ],
        "reconciliations": [
            {
                "benchmark_type": "market_implied",
                "benchmark_source_ref": (
                    f"Wind WSS.close/mkt_cap_ard:{ticker}:{AS_OF_DATE}"
                ),
                "metric_name": "总市值",
                "period": AS_OF_DATE,
                "independent_value": base_case["target_market_cap"],
                "benchmark_value": market_cap,
                "unit": "亿元人民币",
                "decomposition": {
                    "scenario_market_caps": {
                        row["scenario_name"]: row["target_market_cap"]
                        for row in scenario_results
                    },
                    "market_price": price,
                    "market_cap": market_cap,
                },
                "conclusion": (
                    "市场价格只作为冻结后的外部对账，不参与独立利润和目标倍数设定。"
                ),
            }
        ],
    }


def _pb_roe_model(
    snapshot: dict[str, Any],
    ticker: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    current_pb = float(snapshot["wind"]["current"][ticker]["PB_LF"])
    roe = float(spec["normalized_roe"])
    growth = float(spec["long_growth"])
    cost = float(spec["cost_of_equity"])
    justified_pb = (roe - growth) / (cost - growth)
    premium = current_pb / justified_pb - 1.0
    return {
        "run_key": f"{RUN_REF}.{ticker}.pb_roe_diagnostic.v2",
        "skill_name": "company_valuation_modeling",
        "model_name": "PB—ROE可持续回报诊断",
        "model_role": "diagnostic",
        "valuation_date": AS_OF_DATE,
        "assumptions": {
            "normalized_roe_pct": roe,
            "long_growth_pct": growth,
            "cost_of_equity_pct": cost,
        },
        "limitations": (
            "高增长PCB公司的无形客户关系和短期超额增长不能完整反映在账面净资产；"
            "该方法用于检查当前PB要求的回报强度，不作为唯一目标价。"
        ),
        "finalization": "reviewed",
        "inputs": [
            {
                "input_name": "当前市净率",
                "value_num": current_pb,
                "unit": "倍",
                "period_or_as_of_date": AS_OF_DATE,
                "source_ref": f"Wind WSS.pb_lf:{ticker}:{AS_OF_DATE}",
                "input_type": "direct_fact",
                "formula_or_method": "Wind最新账面净资产口径PB",
            },
            {
                "input_name": "可持续ROE假设",
                "value_num": roe,
                "unit": "%",
                "period_or_as_of_date": "长期",
                "source_ref": "; ".join(spec["sources"]),
                "input_type": "expert_assumption",
                "formula_or_method": "结合历史ROE、扩产后利润率和杠杆设定",
            },
            {
                "input_name": "长期增长率",
                "value_num": growth,
                "unit": "%",
                "period_or_as_of_date": "长期",
                "source_ref": "HDI行业供需模型与公司成熟期假设",
                "input_type": "expert_assumption",
                "formula_or_method": "低于显性预测期增长，且不作为永续高增长承诺",
            },
            {
                "input_name": "股权成本",
                "value_num": cost,
                "unit": "%",
                "period_or_as_of_date": AS_OF_DATE,
                "source_ref": "HDI公司估值假设账本",
                "input_type": "expert_assumption",
                "formula_or_method": "人民币权益风险和公司执行风险的研究假设",
            },
        ],
        "outputs": [
            {
                "output_name": "可持续回报支持的市净率",
                "value_num": justified_pb,
                "unit": "倍",
                "period_or_as_of_date": "长期",
                "formula": "合理PB＝（可持续ROE－长期增长率）/（股权成本－长期增长率）",
                "substitution": (
                    f"（{roe:.2f}%－{growth:.2f}%）/"
                    f"（{cost:.2f}%－{growth:.2f}%）＝{justified_pb:.2f}"
                ),
                "dependency_group": "ROE、增长与股权成本",
                "conclusion": (
                    f"当前{current_pb:.2f}倍PB相对诊断值溢价{premium:.1%}；"
                    "溢价是否合理取决于超额增长持续期，不能直接解释为低估或高估。"
                ),
            }
        ],
        "reconciliations": [],
    }


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = _load_snapshot()
    ledger_companies: dict[str, Any] = {}
    export_companies: list[dict[str, Any]] = []
    for ticker, spec in COMPANIES.items():
        identity = snapshot["companies"][ticker]
        base_inputs, base_outputs = _model_rows(snapshot, ticker, spec)
        scenario_inputs, scenario_outputs, scenario_rows = _scenario_model_rows(
            ticker, spec
        )
        inputs = base_inputs + scenario_inputs
        outputs = base_outputs + scenario_outputs
        financial_run_key = f"{RUN_REF}.{ticker}.financial_bridge.v3"
        financial_model = {
            "run_key": financial_run_key,
            "skill_name": "company_financial_modeling",
            "model_name": "HDI经营驱动三情景财务桥",
            "model_role": "core",
            "forecast_start": "2026-01-01",
            "forecast_end": "2028-12-31",
            "valuation_date": AS_OF_DATE,
            "assumptions": {
                "model_level": spec["model_level"],
                "no_consensus_input": True,
                "driver_summary": spec["driver_summary"],
                "scenario_contract": SCENARIO_ASSUMPTIONS[ticker],
            },
            "limitations": spec["key_risk"],
            "finalization": "independent",
            "inputs": inputs,
            "outputs": outputs,
            "reconciliations": [],
            "supersedes_run_keys": [
                f"{RUN_REF}.{ticker}.financial_bridge.v1",
                f"{RUN_REF}.{ticker}.financial_bridge.v2",
            ],
        }
        valuation_model = _valuation_model(snapshot, ticker, spec, scenario_rows)
        valuation_model["supersedes_run_keys"] = [
            f"{RUN_REF}.{ticker}.pe_valuation.v1",
            f"{RUN_REF}.{ticker}.pe_valuation.v2",
        ]
        pb_model = _pb_roe_model(snapshot, ticker, spec)
        pb_model["supersedes_run_keys"] = [
            f"{RUN_REF}.{ticker}.pb_roe_diagnostic.v1"
        ]
        observations: list[dict[str, Any]] = []
        for output in base_outputs:
            metric_map = {
                "营业收入": "revenue",
                "归母净利润": "net_income",
                "经营现金流": "operating_cash_flow",
                "自由现金流近似值": "free_cash_flow",
                "资本开支": "capex",
            }
            year = int(output["period_or_as_of_date"])
            observations.append(
                {
                    "metric_name": metric_map[output["output_name"]],
                    "value_num": output["value_num"],
                    "unit": output["unit"],
                    "currency": "CNY",
                    "period_start": f"{output['period_or_as_of_date']}-01-01",
                    "period_end": f"{output['period_or_as_of_date']}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": f"FY{year - 2025}",
                    "frequency": "annual",
                    "fact_type": "internal_estimate",
                    "as_of_date": AS_OF_DATE,
                    "provider": "internal_model",
                    "raw_feature_name": output["output_name"],
                    "formula": output["formula"],
                    "input_refs": [financial_run_key],
                    "quality_status": "usable",
                    "scenario_name": "base",
                    "model_run_key": financial_run_key,
                }
            )
        metric_labels = {
            "revenue": "营业收入",
            "net_income": "归母净利润",
            "operating_cash_flow": "经营现金流",
            "free_cash_flow": "自由现金流近似值",
            "capex": "资本开支",
        }
        for row in scenario_rows:
            if row["scenario_name"] == "base":
                continue
            for metric_name, output_label in metric_labels.items():
                observations.append(
                    {
                        "metric_name": metric_name,
                        "value_num": row[metric_name],
                        "unit": "亿元人民币",
                        "currency": "CNY",
                        "period_start": f"{row['year']}-01-01",
                        "period_end": f"{row['year']}-12-31",
                        "fiscal_year": int(row["year"]),
                        "fiscal_period": f"FY{int(row['year']) - 2025}",
                        "frequency": "annual",
                        "fact_type": "internal_estimate",
                        "as_of_date": AS_OF_DATE,
                        "provider": "internal_model",
                        "raw_feature_name": (
                            f"{row['scenario_label']}{output_label}"
                        ),
                        "formula": (
                            f"{row['scenario_label']}经营条件：{row['condition']}"
                        ),
                        "input_refs": [financial_run_key],
                        "quality_status": "usable",
                        "scenario_name": row["scenario_name"],
                        "model_run_key": financial_run_key,
                    }
                )
        current = snapshot["wind"]["current"][ticker]
        market_cap = float(current["MKT_CAP_ARD"]) / 1e8
        pe_low, pe_high = (float(value) for value in spec["target_pe"])
        target_pe_mid = (pe_low + pe_high) / 2.0
        implied_profit = market_cap / target_pe_mid
        observations.append(
            {
                "metric_name": "net_income",
                "value_num": implied_profit,
                "unit": "亿元人民币",
                "currency": "CNY",
                "period_start": "2027-01-01",
                "period_end": "2027-12-31",
                "fiscal_year": 2027,
                "fiscal_period": "FY2",
                "frequency": "annual",
                "fact_type": "implied",
                "as_of_date": AS_OF_DATE,
                "provider": "internal_model",
                "raw_feature_name": "当前市值隐含2027年归母净利润",
                "formula": (
                    f"当前市值{market_cap:.2f}亿元÷目标市盈率中值"
                    f"{target_pe_mid:.2f}倍＝{implied_profit:.2f}亿元"
                ),
                "input_refs": [
                    f"Wind WSS.mkt_cap_ard:{ticker}:{AS_OF_DATE}",
                    f"{RUN_REF}.{ticker}.pe_valuation.v3",
                ],
                "quality_status": "usable",
                "scenario_name": "target_pe_midpoint",
                "model_run_key": f"{RUN_REF}.{ticker}.pe_valuation.v3",
            }
        )
        export_companies.append(
            {
                "research_company_id": int(spec["company_id"]),
                "security": {
                    "canonical_name": spec["name"],
                    "ticker": ticker,
                    "market": identity["market"],
                    "listing_status": identity["listing_status"],
                    "reporting_currency": "CNY",
                    "identity_status": "verified",
                },
                "source_snapshots": [],
                "model_runs": [financial_model, valuation_model, pb_model],
                "observations": observations,
            }
        )
        ledger_companies[ticker] = {
            "name": spec["name"],
            "model_level": spec["model_level"],
            "sources": spec["sources"],
            "driver_summary": spec["driver_summary"],
            "forecasts": spec["forecasts"],
            "revenue_uncertainty": spec["revenue_uncertainty"],
            "margin_uncertainty_pp": spec["margin_uncertainty_pp"],
            "target_pe": spec["target_pe"],
            "normalized_roe": spec["normalized_roe"],
            "long_growth": spec["long_growth"],
            "cost_of_equity": spec["cost_of_equity"],
            "key_risk": spec["key_risk"],
            "scenario_contract": SCENARIO_ASSUMPTIONS[ticker],
            "scenario_results": scenario_rows,
        }
    ledger = {
        "ledger_version": "hdi_b_20260726.independent_financial_models.v2",
        "research_run_ref": RUN_REF,
        "as_of_date": AS_OF_DATE,
        "consensus_fields_read": [],
        "method": (
            "先用Wind历史实际值、公司年报/季报和产能节点建立FY1—FY3经营桥，"
            "冻结后才读取Wind west_*及最近两个季度卖方预测对账。"
        ),
        "companies": ledger_companies,
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    export = {
        "export_schema_version": "company_financial_profile_export.v1",
        "research_run_ref": RUN_REF,
        "as_of_date": AS_OF_DATE,
        "source_artifacts": [
            {
                "path": str(SNAPSHOT.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _file_sha256(SNAPSHOT),
            },
            {
                "path": str(LEDGER.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _file_sha256(LEDGER),
            },
        ],
        "companies": export_companies,
    }
    return ledger, export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EXPORT)
    args = parser.parse_args(argv)
    ledger, export = build()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(export, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ledger": str(LEDGER),
                "export": str(output),
                "company_count": len(export["companies"]),
                "model_run_count": sum(
                    len(company["model_runs"]) for company in export["companies"]
                ),
                "consensus_fields_read": ledger["consensus_fields_read"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
