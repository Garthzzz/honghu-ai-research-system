from __future__ import annotations

"""Build and audit Run16's eight-company supplemental financial export.

The builder deliberately has three ordered stages:

1. ``freeze`` reads actual and market observations but excludes ``pe_forward``;
2. ``reconcile`` reads only ``pe_forward`` after the independent model is frozen;
3. ``export`` compiles a ``company_financial_profile_export.v1`` and a full
   arithmetic verification report.

It never writes ``financial.db``.  The resulting export is intended for a
subsequent explicit ``opportunity_profile_export --validate-only`` review.
"""

import argparse
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from tools.financial.opportunity_profile_export import (
    EXPORT_SCHEMA_VERSION,
    validate_export,
)


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data/financial.db"
RUN_DIR = ROOT / "opportunity_lens/research_outputs/20260801_ai_app_full_chain_portfolio_run16"
PACK_PATH = RUN_DIR / "run16_pack_stage.json"
PROTECTED_MODEL_PATH = RUN_DIR / "financial_artifacts/run16_independent_financial_portfolios.json"
PROTECTED_EXPORT_PATH = RUN_DIR / "company_financial_profile_export_v1.json"
SUPPLEMENT_DIR = RUN_DIR / "supplemental_company_financial_profiles"
ACTUAL_PATH = SUPPLEMENT_DIR / "run16_supplemental_actual_market_snapshot.json"
MODEL_PATH = SUPPLEMENT_DIR / "run16_supplemental_independent_models.json"
RECON_PATH = SUPPLEMENT_DIR / "run16_supplemental_pe_forward_reconciliation.json"
EXPORT_PATH = SUPPLEMENT_DIR / "run16_supplemental_company_financial_profile_export_v1.json"
VERIFY_PATH = SUPPLEMENT_DIR / "run16_supplemental_recomputation_verification.json"

AS_OF = "2026-07-30"
RUN_REF = "opportunity_lens:ai_app_full_chain_portfolio:20260801:supplemental_company_profiles"


COMPANIES: dict[str, dict[str, Any]] = {
    "600588.SH": {
        "company_id": 677,
        "name": "用友网络",
        "classification": "loss_turnaround",
        "mechanism": "企业云与BIP合同先经过实施、验收和续费形成收入，再由交付人效、研发投入和回款决定利润与现金流；AI合同本身不能直接等同利润。",
        "evidence_refs": ["app-c28", "app-c29", "app-c14"],
        "evidence_basis": "2025年AI相关合同16.70亿元、约占收入18.2%，但全年仍亏损13.89亿元；2026年一季度收入增长而亏损扩大，因此先验证合同转收入和成本收缩。",
        "revenue_growth": {
            "downside": [0.0, 3.0, 5.0], "base": [6.0, 10.0, 12.0], "upside": [12.0, 16.0, 18.0]
        },
        "net_margin": {
            "downside": [-18.0, -12.0, -6.0], "base": [-10.0, -4.0, 2.0], "upside": [-5.0, 2.0, 8.0]
        },
        "ocf_margin": {"downside": [-2.0, 2.0, 5.0], "base": [5.0, 8.0, 10.0], "upside": [8.0, 12.0, 15.0]},
        "capex_margin": {"downside": [14.0, 12.0, 10.0], "base": [13.0, 10.0, 8.0], "upside": [11.0, 8.0, 6.0]},
        "framework": {
            "applicability": "PB仅作净资产消耗监控；亏损期间Forward PE不适用，PS与盈亏平衡收入只作诊断。",
            "cycle_sensitivity": "收入受大型项目签约、实施和验收周期影响，利润对交付人员利用率和研发费用刚性高度敏感。",
            "asset_intensity": "软件业务物理资产较轻，但项目实施、合同资产和回款占用使现金转换不能按纯订阅软件处理。",
            "basis": "2023—2025连续亏损且2026Q1亏损扩大，不能以负利润或极小预测利润乘PE形成目标价。",
            "price_exposure": "当前定价主要暴露于收入恢复、亏损收窄和AI合同兑现速度，而非已实现的稳定ROE。",
            "profit_driver": "BIP及云订阅增长×合同转收入率×交付毛利改善－研发与销售费用刚性。",
        },
        "buy_trigger": "只有当AI相关合同继续披露可核验收入、FY2026收入达到约97.33亿元、全年亏损收窄至约9.73亿元以内且经营现金流达到约4.87亿元时，才从观察上调风险预算。",
        "sell_trigger": "若FY2026收入仍低于约91.82亿元、亏损扩大到约16.53亿元或经营现金流再次为负，说明AI合同未覆盖基础业务与费用压力，应继续回避或降低仓位。",
    },
    "600570.SH": {
        "company_id": 678,
        "name": "恒生电子",
        "classification": "stable_profit",
        "mechanism": "金融机构IT预算、系统升级和智能体渗透决定收入，项目验收与人员效率决定经营利润；投资收益需与主营盈利分开看。",
        "evidence_refs": ["app-c18", "app-c30", "app-c17"],
        "evidence_basis": "投顾智能体已在20多家机构上线，但相对600多家财富管理客户仍属早期；2025年收入下降且利润改善部分来自投资收益。",
        "revenue_growth": {
            "downside": [-12.0, -3.0, 0.0], "base": [-5.0, 3.0, 6.0], "upside": [0.0, 8.0, 10.0]
        },
        "net_margin": {
            "downside": [14.0, 14.0, 15.0], "base": [18.0, 19.0, 20.0], "upside": [22.0, 23.0, 24.0]
        },
        "ocf_margin": {"downside": [12.0, 13.0, 14.0], "base": [18.0, 18.0, 19.0], "upside": [22.0, 23.0, 24.0]},
        "capex_margin": {"downside": [5.0, 5.0, 5.0], "base": [4.0, 4.0, 4.0], "upside": [3.0, 3.0, 3.0]},
        "framework": {
            "applicability": "Forward PE可作主营恢复的参考；PB—ROE仅诊断，因为投资收益和收入收缩使当期ROE不能直接永续。",
            "cycle_sensitivity": "受资本市场活跃度、金融机构IT预算和项目验收周期影响，中短期收入与利润存在波动。",
            "asset_intensity": "软件研发为主、物理资产较轻，但人员投入和金融客户实施周期构成主要资本约束。",
            "basis": "历史持续盈利且现金流总体为正，允许建立FY2026—FY2028简化桥；但目标价不以单一当前倍数外推。",
            "price_exposure": "当前价格要求主营利润恢复并证明AI产品从上线数量转成收费与续费。",
            "profit_driver": "金融IT预算×客户覆盖×产品升级/AI收费－项目交付成本，并剔除投资收益对可持续利润的扰动。",
        },
        "buy_trigger": "投顾智能体从20多家上线扩展到可核验收费与续费，同时FY2026收入不低于约54.94亿元、归母净利润不低于约9.89亿元、经营现金流不低于约9.89亿元，才支持提高配置。",
        "sell_trigger": "若FY2026收入跌至约50.89亿元以下、利润低于约7.12亿元，或利润改善仍主要来自投资收益而主营现金流低于约6.11亿元，应降低估值与仓位。",
    },
    "600845.SH": {
        "company_id": 679,
        "name": "宝信软件",
        "classification": "stable_profit",
        "mechanism": "钢铁信息化、自动化与数据中心三类业务共同驱动收入；MES和工业AI通过产量、成材率和流程效率为客户创造价值，但各分部资本强度不同。",
        "evidence_refs": ["app-c19", "app-c31"],
        "evidence_basis": "MES覆盖多家钢铁客户，公司案例称合同兑现率提高3%—5%、部分产品废品率下降0.05个百分点；这些客户价值不能把IDC和传统自动化收入都标成AI。",
        "revenue_growth": {
            "downside": [-8.0, 0.0, 3.0], "base": [2.0, 8.0, 10.0], "upside": [8.0, 14.0, 16.0]
        },
        "net_margin": {
            "downside": [10.0, 10.0, 11.0], "base": [13.5, 14.5, 15.5], "upside": [16.0, 18.0, 19.0]
        },
        "ocf_margin": {"downside": [12.0, 13.0, 14.0], "base": [16.0, 17.0, 18.0], "upside": [20.0, 21.0, 22.0]},
        "capex_margin": {"downside": [13.0, 12.0, 11.0], "base": [10.0, 9.0, 8.0], "upside": [8.0, 7.0, 6.0]},
        "framework": {
            "applicability": "Forward PE可作盈利恢复参考；PB—ROE只作分部资本回报诊断，不把历史高ROE直接外推。",
            "cycle_sensitivity": "钢铁资本开支、自动化项目验收和IDC上架节奏共同影响收入与现金流。",
            "asset_intensity": "工业软件较轻，自动化工程与IDC较重，合并PB掩盖分部资本回报差异。",
            "basis": "持续盈利但2025年收入、利润和ROE显著回落，模型采用恢复而非立即回到历史峰值。",
            "price_exposure": "当前估值暴露于工业项目恢复、IDC资本开支回报和利润率修复三项兑现。",
            "profit_driver": "钢铁数字化项目量×单项目价值×验收节奏＋IDC利用率－资本开支和折旧压力。",
        },
        "buy_trigger": "钢铁MES客户价值能继续转成项目验收，IDC资本开支回报单独可核验，且FY2026收入达到约111.91亿元、利润约15.11亿元、自由现金流约6.71亿元以上，才支持提高风险预算。",
        "sell_trigger": "若FY2026收入低于约100.94亿元、利润低于约10.09亿元，或资本开支高于经营现金流使自由现金流转负，说明工业项目与IDC两端均未修复，应降低仓位。",
    },
    "002410.SZ": {
        "company_id": 680,
        "name": "广联达",
        "classification": "profit_recovery",
        "mechanism": "造价、设计和施工软件通过席位、订阅和项目服务变现，AI/BIM的客户价值来自缩短算量时间、降低量差和项目节约；利润取决于续费、提价与费用收缩。",
        "evidence_refs": ["app-c22", "app-c35", "app-c20"],
        "evidence_basis": "2025H1 AI直接合同额超过0.40亿元；公司案例显示算量效率和项目节约，但相对公司收入仍小，不能把效率案例直接变成全公司收入增速。",
        "revenue_growth": {
            "downside": [-6.0, 0.0, 3.0], "base": [0.0, 6.0, 9.0], "upside": [5.0, 12.0, 15.0]
        },
        "net_margin": {
            "downside": [3.0, 4.0, 5.0], "base": [6.0, 8.0, 10.0], "upside": [9.0, 12.0, 14.0]
        },
        "ocf_margin": {"downside": [10.0, 11.0, 12.0], "base": [15.0, 16.0, 17.0], "upside": [19.0, 20.0, 21.0]},
        "capex_margin": {"downside": [7.0, 7.0, 7.0], "base": [5.0, 5.0, 5.0], "upside": [4.0, 4.0, 4.0]},
        "framework": {
            "applicability": "盈利为正，可计算条件Forward PE；PB—ROE只作修复诊断，不能按低谷利润或历史高ROE机械定价。",
            "cycle_sensitivity": "地产与基建投资、客户预算和续费节奏影响收入，费用收缩使利润弹性高于收入。",
            "asset_intensity": "软件业务物理资产较轻，但销售实施与客户回款使现金流存在季节性。",
            "basis": "2023—2025利润从低谷修复但ROE仍低于历史，模型把AI合同作为验证项而非全量增长输入。",
            "price_exposure": "当前价格要求收入止跌、净利率继续修复且经营现金流保持强于利润。",
            "profit_driver": "订阅续费与席位价值＋AI/BIM增量合同－销售研发费用，利润对净利率恢复高度敏感。",
        },
        "buy_trigger": "AI直接合同从2025H1的0.40亿元继续增长并转成续费或提价，且FY2026收入至少稳定在约60.68亿元、利润达到约3.64亿元、经营现金流达到约9.10亿元时，才确认利润修复。",
        "sell_trigger": "若FY2026收入低于约57.04亿元、利润低于约1.71亿元，或AI/BIM只有效率案例而没有续费与现金回款，说明费用收缩而非业务复苏主导利润，应降低仓位。",
    },
    "300624.SZ": {
        "company_id": 681,
        "name": "万兴科技",
        "classification": "loss_turnaround",
        "mechanism": "创意软件通过订阅和应用分发变现，AI原生产品提高使用与客单价的同时增加推理、研发、渠道抽成和获客成本，收入增长不必然带来利润。",
        "evidence_refs": ["app-c33", "app-c16", "app-c15"],
        "evidence_basis": "2025年AI原生应用收入超过1.30亿元、约占总收入8.5%、同比增长超过90%，但公司仍亏损且2026Q1总收入下降2.87%。",
        "revenue_growth": {
            "downside": [-3.0, 2.0, 5.0], "base": [5.0, 10.0, 12.0], "upside": [12.0, 18.0, 20.0]
        },
        "net_margin": {
            "downside": [-10.0, -6.0, -2.0], "base": [-4.0, 0.0, 4.0], "upside": [0.0, 5.0, 9.0]
        },
        "ocf_margin": {"downside": [-3.0, 1.0, 4.0], "base": [2.0, 6.0, 10.0], "upside": [6.0, 11.0, 15.0]},
        "capex_margin": {"downside": [10.0, 9.0, 8.0], "base": [8.0, 7.0, 6.0], "upside": [6.0, 5.0, 4.0]},
        "framework": {
            "applicability": "亏损阶段PE和PB—ROE不适用；PS、盈亏平衡收入和现金流转正时点仅作诊断。",
            "cycle_sensitivity": "受创意工具竞争、应用商店渠道、模型价格和海外合规影响，产品增长与利润率波动较大。",
            "asset_intensity": "物理资产轻，但研发、推理和买量投入构成经济资本，账面净资产低估持续投入。",
            "basis": "2024—2025连续亏损且2026Q1仍亏损，不能以极小预测利润放大PE目标值。",
            "price_exposure": "当前定价暴露于AI收入占比提升、推理成本下降和获客效率改善能否同时发生。",
            "profit_driver": "订阅收入×续费/提价－推理成本－研发与获客投入。",
        },
        "buy_trigger": "AI原生应用收入占比在2025年的8.5%基础上继续提升，同时FY2027收入达到约17.70亿元、实现盈亏平衡并产生约1.06亿元经营现金流，才从观察转为可配置。",
        "sell_trigger": "若FY2026收入低于约14.87亿元、亏损扩大到约1.49亿元，或AI收入增长仍被推理、研发和获客成本吞噬、经营现金流为负，应继续回避。",
    },
    "688256.SH": {
        "company_id": 103,
        "name": "寒武纪",
        "classification": "sharp_inflection",
        "mechanism": "云端训练与推理加速卡及软件平台通过产品交付和生态适配变现，收入受国产算力需求与供应能力推动，利润和现金流对客户集中、产品结构、研发和营运资本高度敏感。",
        "evidence_refs": ["chain-fc-w041"],
        "evidence_basis": "2025年收入和利润出现跃迁，产品覆盖训练、推理和边缘加速，但单年转正不足以证明稳定盈利周期。",
        "revenue_growth": {
            "downside": [45.0, 20.0, 15.0], "base": [85.0, 45.0, 30.0], "upside": [120.0, 65.0, 40.0]
        },
        "net_margin": {
            "downside": [15.0, 15.0, 16.0], "base": [28.0, 27.0, 26.0], "upside": [35.0, 34.0, 32.0]
        },
        "ocf_margin": {"downside": [-2.0, 5.0, 10.0], "base": [10.0, 18.0, 22.0], "upside": [20.0, 28.0, 32.0]},
        "capex_margin": {"downside": [14.0, 12.0, 10.0], "base": [10.0, 8.0, 7.0], "upside": [8.0, 6.0, 5.0]},
        "framework": {
            "applicability": "已转正但盈利历史不足，Forward PE和PB—ROE只作反向诊断；基准估值不输出目标价。",
            "cycle_sensitivity": "产品代际、客户采购、先进制造供应和国产替代节奏会造成收入与利润的大幅波动。",
            "asset_intensity": "芯片设计物理资产相对轻，但研发、流片、存货和客户验证需要大量经济资本。",
            "basis": "2025年首次大幅盈利、2026Q1继续增长，但缺少跨周期稳定利润与现金流，当前PE不能当成熟期倍数。",
            "price_exposure": "当前价格要求高速收入增长延续、利润率保持且现金流由负转正，任何一项落空都会显著压缩估值。",
            "profit_driver": "加速卡出货量×产品价格×毛利率－研发投入－营运资本占用。",
        },
        "buy_trigger": "只有FY2026收入达到约120.20亿元、利润达到约33.66亿元、经营现金流达到约12.02亿元，且客户集中度与存货没有同步恶化，才说明2025年的转折具有持续性。",
        "sell_trigger": "若FY2026收入低于约94.21亿元、利润低于约14.13亿元，或经营现金流再次为负并伴随客户集中/存货上升，应把单年盈利视为不可持续并降低仓位。",
    },
    "688795.SH": {
        "company_id": 327,
        "name": "摩尔线程",
        "classification": "loss_turnaround",
        "mechanism": "通用GPU收入由产品交付、生态适配与客户复购形成，规模放量改善毛利，但研发、供应链、存货和应收决定何时真正跨过盈亏平衡与现金流平衡。",
        "evidence_refs": ["chain-fc-w042"],
        "evidence_basis": "2025年收入约15.05亿元、同比增长约243%，但全年仍亏损约10.01亿元且经营现金流为负；2026Q1小幅盈利不足以证明全年稳定转正。",
        "revenue_growth": {
            "downside": [50.0, 30.0, 20.0], "base": [100.0, 60.0, 35.0], "upside": [160.0, 80.0, 50.0]
        },
        "net_margin": {
            "downside": [-50.0, -30.0, -10.0], "base": [-25.0, -8.0, 5.0], "upside": [-5.0, 8.0, 15.0]
        },
        "ocf_margin": {"downside": [-60.0, -35.0, -15.0], "base": [-35.0, -12.0, 5.0], "upside": [-10.0, 5.0, 15.0]},
        "capex_margin": {"downside": [35.0, 25.0, 18.0], "base": [25.0, 18.0, 12.0], "upside": [18.0, 12.0, 9.0]},
        "framework": {
            "applicability": "全年仍亏损且现金流为负，PE与PB—ROE不适用；采用收入、盈亏平衡和PS反向诊断。",
            "cycle_sensitivity": "产品迭代、供应链、客户集中和国产算力采购节奏使增速与毛利高度波动。",
            "asset_intensity": "芯片设计与软件生态表面轻资产，但研发、流片、库存和客户验证形成高经济资本需求。",
            "basis": "2025年高增长仍未盈利，2026Q1单季小幅盈利不能替代全年现金流验证，禁止用高额前瞻市盈率反推目标价。",
            "price_exposure": "当前价格要求收入数年高速增长、研发费用率下降并实现经营现金流转正。",
            "profit_driver": "GPU出货与复购×毛利率－研发费用－存货和应收占用。",
        },
        "buy_trigger": "FY2026收入达到约30.11亿元、亏损收窄至约7.53亿元以内只是第一道门槛；还需客户复购、毛利稳定，并在FY2028前实现约3.25亿元利润和正经营现金流，才具备配置条件。",
        "sell_trigger": "若FY2026收入低于约22.58亿元、亏损超过约11.29亿元，或经营现金流流出仍超过约13.55亿元且没有客户复购证据，应维持零权重观察。",
    },
    "002335.SZ": {
        "company_id": 222,
        "name": "科华数据",
        "classification": "stable_profit",
        "mechanism": "高端电源、数据中心和清洁能源三类业务共同贡献收入，AI相关机会通过供电模组、液冷设施与IDC需求传导；分部资本强度和现金回报必须拆开判断。",
        "evidence_refs": ["chain-fc-w037"],
        "evidence_basis": "公司披露覆盖数据中心、高端电源和清洁能源，并具备预制式电力模组与液冷设施；AI需求只是其中一部分，不能把合并收入全部按AI增速外推。",
        "revenue_growth": {
            "downside": [3.0, 5.0, 5.0], "base": [12.0, 12.0, 10.0], "upside": [20.0, 18.0, 15.0]
        },
        "net_margin": {
            "downside": [4.0, 4.5, 5.0], "base": [5.5, 6.0, 6.5], "upside": [7.0, 8.0, 9.0]
        },
        "ocf_margin": {"downside": [10.0, 10.0, 11.0], "base": [14.0, 14.0, 15.0], "upside": [18.0, 19.0, 20.0]},
        "capex_margin": {"downside": [7.0, 7.0, 7.0], "base": [5.0, 5.0, 5.0], "upside": [4.0, 4.0, 4.0]},
        "framework": {
            "applicability": "Forward PE可作盈利增长参考；PB—ROE只作低权重诊断，因为三类业务资本强度与周期不同。",
            "cycle_sensitivity": "受数据中心建设、储能/新能源周期、项目验收和回款影响，收入与现金流并不同步。",
            "asset_intensity": "电源设备、IDC和清洁能源均需要营运资本或固定资产，合并PB必须结合ROA和自由现金流。",
            "basis": "公司持续盈利且经营现金流长期为正，允许简化桥；但ROE较低且分部差异大，不输出单一PB目标值。",
            "price_exposure": "当前价格要求AI供电和数据中心需求转成收入，同时维持现金转换并控制新能源业务波动。",
            "profit_driver": "电源/IDC/新能源收入组合×分部毛利－营运资本与资本开支。",
        },
        "buy_trigger": "AI供电、IDC和新能源三类收入能够分部验证，且FY2026收入达到约91.39亿元、利润约5.03亿元、自由现金流约8.23亿元以上，才支持提高配置。",
        "sell_trigger": "若FY2026收入低于约84.05亿元、利润低于约3.36亿元，或数据中心扩张和新能源项目使自由现金流降至约2.52亿元以下，应降低仓位。",
    },
}


ACTUAL_METRICS = {
    "revenue", "net_income", "net_margin", "gross_margin",
    "operating_cash_flow", "capex", "total_equity", "roe", "roa",
    "market_cap", "pb", "ps_ttm", "pe_ttm", "bps_mrq",
}
HISTORICAL_METRICS = {
    "revenue", "net_income", "net_margin", "gross_margin",
    "operating_cash_flow", "capex", "total_equity", "roe", "roa",
}
YEARS = (2026, 2027, 2028)
SCENARIOS = ("downside", "base", "upside")


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _source_index() -> dict[str, dict[str, Any]]:
    pack = _read(PACK_PATH)
    return {str(row["ref"]): row for row in pack.get("sources") or []}


def _db_rows(metric_names: Iterable[str]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    tickers = tuple(COMPANIES)
    metrics = tuple(metric_names)
    placeholders_ticker = ",".join("?" for _ in tickers)
    placeholders_metric = ",".join("?" for _ in metrics)
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        securities = {
            str(row["ticker"]): dict(row)
            for row in conn.execute(
                f"SELECT * FROM financial_security WHERE ticker IN ({placeholders_ticker})",
                tickers,
            )
        }
        rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT o.*, s.ticker, ss.title AS source_title,
                       ss.publisher AS source_publisher, ss.source_ref
                  FROM financial_observation o
                  JOIN financial_security s ON s.id=o.security_id
             LEFT JOIN financial_source_snapshot ss ON ss.id=o.source_snapshot_id
                 WHERE s.ticker IN ({placeholders_ticker})
                   AND o.metric_name IN ({placeholders_metric})
                   AND o.value_num IS NOT NULL
                   AND o.quality_status='usable'
                """,
                (*tickers, *metrics),
            )
        ]
    finally:
        conn.close()
    if set(securities) != set(tickers):
        raise ValueError(f"证券身份不完整: missing={sorted(set(tickers)-set(securities))}")
    return securities, rows


def _provider_rank(row: dict[str, Any]) -> tuple[int, int]:
    provider = str(row.get("provider") or "").lower()
    return ({"wind": 0, "tushare": 1, "legacy": 2}.get(provider, 3), -int(row.get("id") or 0))


def _select(rows: list[dict[str, Any]], ticker: str, metric: str, *, period_end: str | None = None) -> dict[str, Any] | None:
    candidates = [
        row for row in rows
        if row["ticker"] == ticker and row["metric_name"] == metric
        and (period_end is None or row.get("period_end") == period_end)
    ]
    if not candidates:
        return None
    if period_end is None:
        latest = max(str(row.get("period_end") or row.get("as_of_date") or "") for row in candidates)
        candidates = [row for row in candidates if str(row.get("period_end") or row.get("as_of_date") or "") == latest]
    candidates.sort(key=_provider_rank)
    return candidates[0]


def _compact_observation(row: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "metric_name", "value_num", "value_text", "unit", "currency",
        "period_start", "period_end", "fiscal_year", "fiscal_period",
        "frequency", "fact_type", "as_of_date", "announcement_date",
        "provider", "raw_feature_name", "formula", "quality_status",
        "scenario_name", "source_title", "source_publisher", "source_ref",
    )
    return {key: row.get(key) for key in keep}


def freeze() -> dict[str, Any]:
    if "pe_forward" in ACTUAL_METRICS:
        raise AssertionError("freeze stage must not request pe_forward")
    securities, rows = _db_rows(ACTUAL_METRICS)
    source_index = _source_index()
    protected = {
        _rel(path): _sha(path)
        for path in (PACK_PATH, PROTECTED_MODEL_PATH, PROTECTED_EXPORT_PATH)
        if path.is_file()
    }
    actual_companies: dict[str, Any] = {}
    for ticker, config in COMPANIES.items():
        observations: list[dict[str, Any]] = []
        for metric in sorted(ACTUAL_METRICS):
            metric_rows = [r for r in rows if r["ticker"] == ticker and r["metric_name"] == metric]
            if not metric_rows:
                continue
            if metric in HISTORICAL_METRICS:
                for year in range(2021, 2026):
                    selected = _select(rows, ticker, metric, period_end=f"{year}-12-31")
                    if selected:
                        observations.append(_compact_observation(selected))
                for period in ("2025-03-31", "2026-03-31"):
                    selected = _select(rows, ticker, metric, period_end=period)
                    if selected:
                        observations.append(_compact_observation(selected))
            else:
                selected = _select(rows, ticker, metric)
                if selected:
                    observations.append(_compact_observation(selected))
        evidence = []
        for ref in config["evidence_refs"]:
            if ref not in source_index:
                raise ValueError(f"{ticker} Run16 evidence ref missing: {ref}")
            source = source_index[ref]
            evidence.append({
                "ref": ref,
                "title": source.get("title"),
                "publisher": source.get("publisher"),
                "published_at": source.get("published_at"),
                "excerpt": source.get("excerpt"),
                "independence_key": source.get("independence_key"),
            })
        actual_companies[ticker] = {
            "security": securities[ticker],
            "observations": observations,
            "run16_evidence": evidence,
        }
    actual_payload = {
        "schema_version": "run16.supplemental_actual_market_snapshot.v1",
        "as_of_date": AS_OF,
        "database": _rel(DB_PATH),
        "read_contract": {
            "sqlite_mode": "read_only",
            "requested_metrics": sorted(ACTUAL_METRICS),
            "external_consensus_excluded": True,
            "provider_priority": ["wind", "tushare", "legacy"],
        },
        "protected_artifacts_before": protected,
        "companies": actual_companies,
    }
    _write(ACTUAL_PATH, actual_payload)
    model_payload = _build_independent_model(actual_payload)
    _write(MODEL_PATH, model_payload)
    return {
        "stage": "freeze",
        "actual_path": str(ACTUAL_PATH), "actual_sha256": _sha(ACTUAL_PATH),
        "model_path": str(MODEL_PATH), "model_sha256": _sha(MODEL_PATH),
        "companies": len(model_payload["companies"]),
    }


def _value(company: dict[str, Any], metric: str, period_end: str | None = None) -> float | None:
    rows = [r for r in company["observations"] if r["metric_name"] == metric]
    if period_end is not None:
        rows = [r for r in rows if r.get("period_end") == period_end]
    if not rows:
        return None
    rows.sort(key=lambda r: str(r.get("period_end") or r.get("as_of_date") or ""))
    return _finite(rows[-1].get("value_num"))


def _scenario(config: dict[str, Any], baseline: dict[str, float], scenario: str) -> dict[str, Any]:
    revenue = baseline["revenue_2025"]
    equity = baseline["parent_equity_proxy"]
    years: dict[str, Any] = {}
    for index, year in enumerate(YEARS):
        growth = float(config["revenue_growth"][scenario][index])
        margin = float(config["net_margin"][scenario][index])
        ocf_margin = float(config["ocf_margin"][scenario][index])
        capex_margin = float(config["capex_margin"][scenario][index])
        opening_equity = equity
        revenue = revenue * (1.0 + growth / 100.0)
        net_income = revenue * margin / 100.0
        ocf = revenue * ocf_margin / 100.0
        capex = revenue * capex_margin / 100.0
        fcf = ocf - capex
        # No dividend/buyback/other-equity information exists in the permitted
        # snapshot.  Keeping all profit is a transparent book-value proxy, not
        # a claim about actual capital allocation.
        equity = opening_equity + net_income
        average_equity = (opening_equity + equity) / 2.0
        roe = net_income / average_equity * 100.0 if average_equity > 0 else None
        years[str(year)] = {
            "revenue_growth_pct": round(growth, 4),
            "revenue_100m_cny": round(revenue, 6),
            "net_margin_pct": round(margin, 4),
            "parent_net_income_100m_cny": round(net_income, 6),
            "ocf_margin_pct": round(ocf_margin, 4),
            "ocf_100m_cny": round(ocf, 6),
            "capex_margin_pct": round(capex_margin, 4),
            "capex_100m_cny": round(capex, 6),
            "fcf_100m_cny": round(fcf, 6),
            "opening_parent_equity_proxy_100m_cny": round(opening_equity, 6),
            "ending_parent_equity_proxy_100m_cny": round(equity, 6),
            "roe_proxy_pct": round(roe, 6) if roe is not None else None,
            "equity_bridge_formula": "期末归母权益代理=期初归母权益代理+归母净利润；因缺少允许口径的分红、回购及其他权益变动，本桥不扣减这些项目。",
        }
    return years


def _build_independent_model(actual: dict[str, Any]) -> dict[str, Any]:
    companies: dict[str, Any] = {}
    for ticker, config in COMPANIES.items():
        raw = actual["companies"][ticker]
        revenue_2025 = _value(raw, "revenue", "2025-12-31")
        net_income_2025 = _value(raw, "net_income", "2025-12-31")
        gross_margin_2025 = _value(raw, "gross_margin", "2025-12-31")
        market_cap = _value(raw, "market_cap")
        pb = _value(raw, "pb")
        ps = _value(raw, "ps_ttm")
        pe_ttm = _value(raw, "pe_ttm")
        bps = _value(raw, "bps_mrq")
        if revenue_2025 is None or net_income_2025 is None or market_cap is None or pb is None:
            raise ValueError(f"{ticker} missing required actual/market baseline")
        parent_equity_proxy = market_cap / pb
        baseline = {
            "revenue_2025": revenue_2025,
            "net_income_2025": net_income_2025,
            "gross_margin_2025_pct": gross_margin_2025,
            "market_cap_100m_cny": market_cap,
            "pb": pb,
            "ps_ttm": ps,
            "pe_ttm": pe_ttm,
            "bps_mrq": bps,
            "parent_equity_proxy": parent_equity_proxy,
            "parent_equity_proxy_formula": "Wind当前总市值÷Wind当前PB；用于保持PB分母口径一致，不替代法定归母权益披露。",
        }
        scenarios = {name: _scenario(config, baseline, name) for name in SCENARIOS}
        base_2027 = scenarios["base"]["2027"]
        base_2028 = scenarios["base"]["2028"]
        stable = config["classification"] in {"stable_profit", "profit_recovery"}
        current_pe_on_fy2027 = (
            market_cap / base_2027["parent_net_income_100m_cny"]
            if base_2027["parent_net_income_100m_cny"] > 0 else None
        )
        current_ps_on_fy2028 = market_cap / base_2028["revenue_100m_cny"]
        pb_reverse_required_roe = 3.0 + pb * (9.5 - 3.0)
        break_even = None
        if net_income_2025 < 0 and gross_margin_2025 and gross_margin_2025 > 0:
            optimistic = revenue_2025 + abs(net_income_2025) / (gross_margin_2025 / 100.0)
            conservative = revenue_2025 + abs(net_income_2025) / (gross_margin_2025 / 200.0)
            break_even = {
                "range_low_100m_cny": round(optimistic, 6),
                "range_high_100m_cny": round(conservative, 6),
                "formula": "盈亏平衡收入=FY2025收入+FY2025亏损÷增量贡献率；区间分别取FY2025毛利率和其50%作为增量贡献率。",
                "limitation": "未取得费用逐项可变/固定拆分，因此只是经营阈值，不是收入预测或估值目标。",
            }
        companies[ticker] = {
            "company_id": config["company_id"],
            "name": config["name"],
            "classification": config["classification"],
            "economic_mechanism": config["mechanism"],
            "evidence_refs": config["evidence_refs"],
            "evidence_basis": config["evidence_basis"],
            "baseline": baseline,
            "assumption_ledger": {
                "revenue_growth_pct": config["revenue_growth"],
                "net_margin_pct": config["net_margin"],
                "ocf_margin_pct": config["ocf_margin"],
                "capex_margin_pct": config["capex_margin"],
                "assumption_type": "internal_expert_scenario",
                "method": "以FY2025实际、2026Q1方向、历史波动和Run16公司合同/客户价值证据设定三情景；数字不是外部事实。",
            },
            "scenarios": scenarios,
            "valuation_applicability": {
                "forward_pe": "applicable_as_diagnostic" if stable else "not_applicable_for_target_price",
                "pb_roe": "diagnostic_only" if stable else "not_applicable_for_target_price",
                "ps": "secondary_diagnostic" if stable else "primary_reverse_diagnostic",
                "reason": config["framework"]["basis"],
            },
            "valuation_diagnostics": {
                "current_market_cap_100m_cny": round(market_cap, 6),
                "current_pe_on_independent_fy2027": round(current_pe_on_fy2027, 6) if current_pe_on_fy2027 else None,
                "current_ps_on_independent_fy2028": round(current_ps_on_fy2028, 6),
                "current_pb": round(pb, 6),
                "pb_reverse_required_roe_pct": round(pb_reverse_required_roe, 6),
                "pb_reverse_formula": "当前PB反向要求的ROE=g+PB×(Ke−g)，统一压力诊断假设Ke=9.5%、g=3.0%。",
                "break_even_revenue": break_even,
            },
            "pb_framework": {
                **config["framework"],
                "tags": [
                    {"label": "盈利驱动", "basis": config["framework"]["profit_driver"]},
                    {"label": "估值门禁", "basis": config["framework"]["applicability"]},
                    {"label": "数据边界", "basis": "模型只使用financial.db已有Wind实际/市场字段与Run16既有证据；未来参数是显式内部情景。"},
                ],
            },
            "buy_trigger": config["buy_trigger"],
            "sell_trigger": config["sell_trigger"],
            "limitations": [
                "没有使用Wind一致预期或前瞻市盈率设定内部增长、利润率或估值结论。",
                "未取得分业务完整三表、分红/回购和客户级回款计划，权益桥采用零分配代理。",
                "该补充模型不回写Run16组合权重，也不是最初Run16组合输入。",
            ],
        }
    return {
        "schema_version": "run16.supplemental_independent_models.v1",
        "research_run_ref": RUN_REF,
        "as_of_date": AS_OF,
        "actual_snapshot_sha256": _sha(ACTUAL_PATH),
        "freeze_control": {
            "independent_before_external_reconciliation": True,
            "external_consensus_used_in_assumptions": False,
            "supplemental_only": True,
            "run16_portfolio_weight_input": False,
        },
        "companies": companies,
    }


def reconcile() -> dict[str, Any]:
    if not MODEL_PATH.is_file() or not ACTUAL_PATH.is_file():
        raise FileNotFoundError("run freeze stage before reconcile")
    model_sha = _sha(MODEL_PATH)
    securities, rows = _db_rows(("pe_forward",))
    model = _read(MODEL_PATH)
    reconciliations: dict[str, Any] = {}
    for ticker, company in model["companies"].items():
        row = _select(rows, ticker, "pe_forward")
        if not row:
            reconciliations[ticker] = {
                "status": "missing",
                "reason": "financial.db没有可用pe_forward；不以其他倍数补造。",
            }
            continue
        pe_forward = float(row["value_num"])
        market_cap = float(company["baseline"]["market_cap_100m_cny"])
        implied_profit = market_cap / pe_forward if pe_forward > 0 else None
        fy2026_profit = company["scenarios"]["base"]["2026"]["parent_net_income_100m_cny"]
        difference_pct = (
            (fy2026_profit - implied_profit) / abs(implied_profit) * 100.0
            if implied_profit not in {None, 0.0} else None
        )
        reconciliations[ticker] = {
            "status": "usable" if pe_forward > 0 else "not_meaningful",
            "provider": row.get("provider"),
            "raw_feature_name": row.get("raw_feature_name"),
            "period_end": row.get("period_end"),
            "as_of_date": row.get("as_of_date"),
            "pe_forward": pe_forward,
            "market_cap_100m_cny": market_cap,
            "market_implied_forward_profit_100m_cny": round(implied_profit, 6) if implied_profit else None,
            "independent_fy2026_profit_100m_cny": fy2026_profit,
            "difference_pct": round(difference_pct, 6) if difference_pct is not None else None,
            "formula": "Wind前瞻市盈率隐含利润=当前总市值÷Wind前瞻市盈率。",
            "interpretation": (
                "仅用于冻结后外部对账；对亏损或刚转折公司，极高前瞻市盈率反映预测利润分母很小，"
                "不能作为目标倍数或目标价。"
            ),
            "source": _compact_observation(row),
        }
    payload = {
        "schema_version": "run16.supplemental_pe_forward_reconciliation.v1",
        "research_run_ref": RUN_REF,
        "as_of_date": AS_OF,
        "independent_model_sha256": model_sha,
        "sequence_control": "本文件在独立模型落盘并取得SHA256后生成；只读取financial.db中的pe_forward。",
        "companies": reconciliations,
    }
    _write(RECON_PATH, payload)
    return {
        "stage": "reconcile", "path": str(RECON_PATH),
        "sha256": _sha(RECON_PATH), "companies": len(reconciliations),
    }


def _artifact_ref(path: Path, pointer: str) -> str:
    return f"{_sha(path)}#{pointer}"


def _input(name: str, value: float | None, unit: str, period: str, source_ref: str, method: str, *, value_text: str | None = None, input_type: str = "expert_assumption") -> dict[str, Any]:
    return {
        "input_name": name, "value_num": value, "value_text": value_text,
        "unit": unit, "period_or_as_of_date": period, "source_ref": source_ref,
        "input_type": input_type, "formula_or_method": method,
        "sensitivity_note": "收入增速、净利率、现金转换率和资本开支率按公司及情景分别变化。",
        "limitation_note": "未来数值是内部研究情景，不是公司指引、Wind一致预期或卖方预测。",
    }


def _output(name: str, unit: str, period: str, formula: str, substitution: str, *, value: float | None = None, value_text: str | None = None, low: float | None = None, high: float | None = None, group: str = "独立模型", conclusion: str = "研究估计") -> dict[str, Any]:
    return {
        "output_name": name, "value_num": value, "value_text": value_text,
        "range_low": low, "range_high": high, "unit": unit,
        "period_or_as_of_date": period, "formula": formula,
        "substitution": substitution, "dependency_group": group,
        "conclusion": conclusion,
    }


def _observation(metric: str, value: float, unit: str, fact_type: str, provider: str, raw_feature: str, snapshot: str, *, year: int | None = None, scenario: str = "reported", model_key: str | None = None, frequency: str = "annual", formula: str | None = None, input_refs: list[str] | None = None) -> dict[str, Any]:
    return {
        "metric_name": metric, "value_num": float(value), "unit": unit,
        "currency": "CNY" if "人民币" in unit else None,
        "period_end": f"{year}-12-31" if year else AS_OF,
        "fiscal_year": year, "fiscal_period": f"FY{year-2025}" if year else None,
        "frequency": frequency, "fact_type": fact_type, "as_of_date": AS_OF,
        "provider": provider, "raw_feature_name": raw_feature,
        "formula": formula, "input_refs": list(input_refs or []), "quality_status": "usable",
        "scenario_name": scenario, "source_snapshot_key": snapshot,
        "model_run_key": model_key,
    }


def _financial_model(ticker: str, company: dict[str, Any], recon: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run_key = f"ol16supp:{ticker}:independent_financial_bridge:v1"
    baseline = company["baseline"]
    inputs = [
        _input("FY2025营业收入", baseline["revenue_2025"], "亿元人民币", "2025", _artifact_ref(ACTUAL_PATH, f"companies.{ticker}.revenue.2025"), "financial.db Wind实际值。", input_type="direct_fact"),
        _input("FY2025归母净利润", baseline["net_income_2025"], "亿元人民币", "2025", _artifact_ref(ACTUAL_PATH, f"companies.{ticker}.net_income.2025"), "financial.db Wind实际值。", input_type="direct_fact"),
        _input("经营传导机制", None, "文字", "2026—2028", _artifact_ref(PACK_PATH, f"sources.{company['evidence_refs'][0]}"), "Run16既有合同、客户价值和业务边界证据。", value_text=company["economic_mechanism"], input_type="derived_fact"),
        _input("情景参数来源", None, "文字", "2026—2028", _artifact_ref(MODEL_PATH, f"companies.{ticker}.assumption_ledger"), "FY2025实际、2026Q1方向、历史波动与Run16证据的显式内部情景。", value_text=company["evidence_basis"]),
    ]
    yearly_rationales = {
        2026: "以FY2025实际和2026Q1同比方向为近期锚；季度季节性明显时不直接年化，并用Run16合同/客户价值证据约束增量。",
        2027: "在FY2026经营验证基础上假设合同转收入、费用率或产能利用率继续变化；这是内部基准情景，不是外部一致预期。",
        2028: "只在客户复购、利润率与现金流持续改善时延续中期路径；上行和下行情景同步保留，避免把单年转折永续化。",
    }
    for year in YEARS:
        row = company["scenarios"]["base"][str(year)]
        inputs.append(_input(
            f"FY{year}基准经营假设",
            None,
            "文字",
            str(year),
            _artifact_ref(MODEL_PATH, f"companies.{ticker}.assumption_ledger"),
            f"{yearly_rationales[year]} 公司证据锚：{company['evidence_basis']}",
            value_text=(
                f"收入增长{row['revenue_growth_pct']:.2f}%，归母净利率{row['net_margin_pct']:.2f}%，"
                f"经营现金流率{row['ocf_margin_pct']:.2f}%，资本开支率{row['capex_margin_pct']:.2f}%。"
            ),
        ))
    outputs: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for year in YEARS:
        base = company["scenarios"]["base"][str(year)]
        down = company["scenarios"]["downside"][str(year)]
        up = company["scenarios"]["upside"][str(year)]
        fields = (
            ("revenue_100m_cny", "营业收入", "revenue", "亿元人民币", "上年收入×(1+收入增速)"),
            ("parent_net_income_100m_cny", "归母净利润", "net_income", "亿元人民币", "营业收入×归母净利率"),
            ("ocf_100m_cny", "经营现金流", "operating_cash_flow", "亿元人民币", "营业收入×经营现金流率"),
            ("capex_100m_cny", "资本开支", "capex", "亿元人民币", "营业收入×资本开支率"),
            ("fcf_100m_cny", "自由现金流", "free_cash_flow", "亿元人民币", "经营现金流−资本开支"),
            ("ending_parent_equity_proxy_100m_cny", "期末归母权益代理", "book_value", "亿元人民币", "期初归母权益代理+归母净利润；暂不扣分红/回购/其他权益"),
            ("roe_proxy_pct", "净资产收益率代理", "roe", "%", "归母净利润÷平均归母权益代理"),
        )
        for field, label, metric, unit, formula in fields:
            value = base.get(field)
            low = down.get(field)
            high = up.get(field)
            if value is None:
                continue
            range_low = min(low, value, high) if low is not None and high is not None else None
            range_high = max(low, value, high) if low is not None and high is not None else None
            outputs.append(_output(
                f"{year}年{label}", unit, str(year), formula,
                f"基准={value:.2f}{unit}；下行/上行={range_low:.2f}/{range_high:.2f}{unit}",
                value=value, low=range_low, high=range_high,
                conclusion="独立情景；区间反映经营参数而非统计置信区间。",
            ))
            observations.append(_observation(
                metric, value, unit, "internal_estimate", "internal_model",
                f"run16_supplement.base.{field}", "independent_model",
                year=year, scenario="base", model_key=run_key,
                formula=formula,
                input_refs=[_artifact_ref(MODEL_PATH, f"companies.{ticker}.scenarios.base.{year}.{field}")],
            ))
    break_even = company["valuation_diagnostics"].get("break_even_revenue")
    if break_even:
        outputs.append(_output(
            "FY2025成本结构下盈亏平衡收入阈值", "亿元人民币", "诊断",
            break_even["formula"],
            f"{break_even['range_low_100m_cny']:.2f}—{break_even['range_high_100m_cny']:.2f}亿元",
            low=break_even["range_low_100m_cny"], high=break_even["range_high_100m_cny"],
            group="盈亏平衡诊断", conclusion=break_even["limitation"],
        ))
    reconciliations = []
    if recon.get("status") == "usable":
        reconciliations.append({
            "benchmark_type": "consensus",
            "benchmark_source_ref": _artifact_ref(RECON_PATH, f"companies.{ticker}"),
            "metric_name": "net_income", "period": "FY2026",
            "independent_value": company["scenarios"]["base"]["2026"]["parent_net_income_100m_cny"],
            "benchmark_value": recon["market_implied_forward_profit_100m_cny"],
            "unit": "亿元人民币",
            "decomposition": {
                "pe_forward": recon["pe_forward"],
                "difference_pct": recon["difference_pct"],
                "formula": recon["formula"],
                "sequence_control": "independent model frozen before pe_forward read",
            },
            "conclusion": recon["interpretation"],
        })
    return ({
        "run_key": run_key,
        "skill_name": "company_financial_modeling",
        "model_name": f"Run16补充：{company['name']}公司特定财务桥与盈亏诊断",
        "model_role": "primary",
        "forecast_start": "2026", "forecast_end": "2028", "valuation_date": AS_OF,
        "assumptions": {
            "model_level": "FY2026—FY2028简化财务桥" if company["classification"] in {"stable_profit", "profit_recovery"} else "收入—盈亏平衡与现金流转折模型",
            "independent_before_pe_forward": True,
            "economic_mechanism": company["economic_mechanism"],
            "supplemental_only": True,
            "run16_portfolio_weight_input": False,
        },
        "limitations": "；".join(company["limitations"]),
        "finalization": "independent", "inputs": inputs, "outputs": outputs,
        "reconciliations": reconciliations,
    }, observations)


def _valuation_models(ticker: str, company: dict[str, Any], recon: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    diagnostics = company["valuation_diagnostics"]
    framework = company["pb_framework"]
    stable = company["classification"] in {"stable_profit", "profit_recovery"}
    forward_pe_text = (
        "公司仍有正利润基础，前瞻市盈率可用于当前定价诊断，但本补充模型不把它作为目标倍数。"
        if stable else
        "亏损或盈利历史不足，前瞻市盈率不适合生成目标价，只保留冻结后的反向利润对账。"
    )
    fy27 = company["scenarios"]["base"]["2027"]
    fy28 = company["scenarios"]["base"]["2028"]
    market_cap = company["baseline"]["market_cap_100m_cny"]
    reconciliation_text = (
        f"Wind前瞻市盈率为{recon['pe_forward']:.2f}倍，对应隐含利润{recon['market_implied_forward_profit_100m_cny']:.2f}亿元；"
        f"独立FY2026利润与其差异{recon['difference_pct']:.2f}%。"
        if recon.get("status") == "usable" else "financial.db未提供可用前瞻市盈率，未补造外部对账。"
    )
    if stable:
        valuation_analysis = (
            f"当前市值{market_cap:.2f}亿元，对独立FY2027利润{fy27['parent_net_income_100m_cny']:.2f}亿元的PE为"
            f"{diagnostics['current_pe_on_independent_fy2027']:.2f}倍；当前PB {diagnostics['current_pb']:.2f}倍在Ke=9.5%、g=3.0%的诊断式下"
            f"反向要求的ROE约{diagnostics['pb_reverse_required_roe_pct']:.2f}%。这只是统一资本成本假设下的压力门槛，不是可持续ROE预测。{reconciliation_text}"
        )
        conclusion = "公司仍有正利润与现金流基础，但当前估值是否合理取决于FY2026—FY2028增长和利润率路径能否兑现；不输出缺少历史倍数带支持的机械目标价。"
    else:
        valuation_analysis = (
            f"当前市值{market_cap:.2f}亿元，对独立FY2028收入{fy28['revenue_100m_cny']:.2f}亿元的PS仍为"
            f"{diagnostics['current_ps_on_independent_fy2028']:.2f}倍。{reconciliation_text}"
        )
        conclusion = "亏损或单年急剧转折阶段不使用PE/PB—ROE造目标价；只比较收入、盈亏平衡、现金流和当前价格隐含要求。"
    summary = {
        "ready": True,
        "conclusion": conclusion,
        "operating_analysis": (
            f"FY2025收入{company['baseline']['revenue_2025']:.2f}亿元、归母净利润{company['baseline']['net_income_2025']:.2f}亿元；"
            f"独立FY2026—FY2028收入为" + "/".join(f"{company['scenarios']['base'][str(y)]['revenue_100m_cny']:.2f}" for y in YEARS) +
            "亿元，归母净利润为" + "/".join(f"{company['scenarios']['base'][str(y)]['parent_net_income_100m_cny']:.2f}" for y in YEARS) +
            f"亿元。{company['economic_mechanism']}"
        ),
        "valuation_analysis": valuation_analysis,
        "buy_point_analysis": company["buy_trigger"],
        "sell_point_analysis": company["sell_trigger"],
        "difference_causes": [
            "内部模型不读取前瞻市盈率来设定收入和利润率，外部倍数只在冻结后对账。",
            "Run16合同或客户价值能证明需求，但合同确认、成本、资本开支和回款决定股东利润。",
        ],
        "future_view": "未来12个月看收入确认、费用率和现金流；三年看客户复购、竞争壁垒、资本回报和高增长持续期。",
        "positive_trigger": "连续两个报告期达到独立基准并且市场隐含利润没有更快上修。",
    }
    workbench = {
        "simple_ready": stable,
        "detailed_ready": False,
        "default_mode": "simple",
        "reason": "盈利稳定/修复公司可用净利润与权益代理做简化情景；亏损与急剧转折公司不自动生成目标PB。" if stable else "亏损或盈利历史不足，简化PB输入台关闭，避免伪精确目标价。",
        "simple": {
            "opening_book_value_cny_100m": company["baseline"]["parent_equity_proxy"],
            "current_pb": company["baseline"]["pb"],
            "target_pb": None,
            "years": [
                {
                    "fiscal_year": year,
                    "net_income_cny_100m": company["scenarios"]["base"][str(year)]["parent_net_income_100m_cny"],
                    "estimated_cash_dividend_cny_100m": 0.0,
                    "timing_basis": "未取得允许口径的分红/回购输入，零分配仅用于权益桥代理。",
                }
                for year in YEARS
            ] if stable else [],
            "pb_presets": {"current": company["baseline"]["pb"]},
        },
        "detailed": {
            "available_fields": ["收入", "归母净利润", "经营现金流", "资本开支", "归母权益代理"],
            "missing_required_fields": ["分业务完整三表", "分红与回购计划", "客户级回款与营运资本计划"],
        },
    }
    valuation_key = f"ol16supp:{ticker}:valuation_diagnostic:v1"
    outputs = [
        _output(
            "当前市值对应独立FY2028收入的PS", "倍", "2028",
            "当前总市值÷独立FY2028营业收入",
            f"{market_cap:.2f}÷{fy28['revenue_100m_cny']:.2f}={diagnostics['current_ps_on_independent_fy2028']:.2f}倍",
            value=diagnostics["current_ps_on_independent_fy2028"], group="反向估值", conclusion="解释当前价格要求，不是目标倍数。",
        ),
        _output(
            "当前PB反向要求的ROE（仅作压力诊断）", "%", AS_OF,
            "g+PB×(Ke−g)，Ke=9.5%、g=3.0%",
            f"3.0%+{diagnostics['current_pb']:.2f}×(9.5%−3.0%)={diagnostics['pb_reverse_required_roe_pct']:.2f}%",
            value=diagnostics["pb_reverse_required_roe_pct"], group="PB—ROE压力诊断",
            conclusion=(
                "该异常高值与亏损或急剧转折期ROE不匹配，证明PB—ROE法不适用；它不是可持续ROE预测。"
                if not stable else
                "这是当前PB在统一资本成本和长期增长假设下反向要求的ROE，不是可持续ROE预测或目标值。"
            ),
        ),
        _output(
            "前瞻市盈率适用性", "文字", AS_OF, "按盈利稳定性、利润口径和周期门禁判断",
            forward_pe_text, value_text=forward_pe_text,
            group="方法适用性", conclusion=company["valuation_applicability"]["reason"],
        ),
    ]
    if diagnostics.get("current_pe_on_independent_fy2027") is not None:
        outputs.append(_output(
            "当前市值对应独立FY2027利润的市盈率", "倍", "2027",
            "当前总市值÷独立FY2027归母净利润",
            f"{market_cap:.2f}÷{fy27['parent_net_income_100m_cny']:.2f}={diagnostics['current_pe_on_independent_fy2027']:.2f}倍",
            value=diagnostics["current_pe_on_independent_fy2027"], group="前瞻市盈率诊断",
            conclusion="仅为当前市场定价诊断，不是目标倍数或目标价。",
        ))
    valuation_model = {
        "run_key": valuation_key,
        "skill_name": "company_valuation_modeling",
        "model_name": f"Run16补充：{company['name']}估值适用性与公司页综合判断",
        "model_role": "reference", "forecast_start": "2026", "forecast_end": "2028", "valuation_date": AS_OF,
        "assumptions": {
            "pb_framework": framework,
            "scenario_workbench": workbench,
            "company_detail_summary": summary,
            "core_method": "Forward PE诊断" if stable else "PS与盈亏平衡反向诊断",
            "supplemental_only": True,
            "run16_portfolio_weight_input": False,
        },
        "limitations": "不以当前pe_forward作为目标倍数；没有可靠历史倍数带和分部完整模型时不输出机械目标价。",
        "finalization": "reviewed",
        "inputs": [
            _input("当前总市值", market_cap, "亿元人民币", AS_OF, _artifact_ref(ACTUAL_PATH, f"companies.{ticker}.market_cap"), "financial.db Wind市场快照。", input_type="direct_fact"),
            _input("独立FY2027归母净利润", fy27["parent_net_income_100m_cny"], "亿元人民币", "2027", _artifact_ref(MODEL_PATH, f"companies.{ticker}.scenarios.base.2027"), "冻结内部模型。", input_type="derived_fact"),
        ],
        "outputs": outputs, "reconciliations": [],
    }
    implied_key = f"ol16supp:{ticker}:market_implied:v1"
    if recon.get("status") == "usable":
        implied_profit = recon["market_implied_forward_profit_100m_cny"]
        implied_outputs = [_output(
            "Wind前瞻市盈率隐含归母净利润", "亿元人民币", "FY1",
            "当前总市值÷Wind前瞻市盈率",
            f"{market_cap:.2f}÷{recon['pe_forward']:.2f}={implied_profit:.2f}亿元",
            value=implied_profit, group="市场隐含", conclusion=recon["interpretation"],
        )]
    else:
        implied_profit = None
        implied_outputs = [_output(
            "Wind前瞻市盈率隐含归母净利润", "文字", "FY1",
            "当前总市值÷Wind前瞻市盈率", "缺少可用前瞻市盈率，不计算。",
            value_text="没有可用外部倍数", group="市场隐含", conclusion="不补造。",
        )]
    implied_model = {
        "run_key": implied_key,
        "skill_name": "company_valuation_modeling",
        "model_name": f"Run16补充：{company['name']}当前市场隐含预期",
        "model_role": "diagnostic", "forecast_start": "2026", "forecast_end": "2026", "valuation_date": AS_OF,
        "assumptions": {"supplemental_only": True, "benchmark": "独立模型冻结后读取Wind前瞻市盈率"},
        "limitations": "前瞻市盈率隐含利润不是市场唯一真实预期；对亏损或转折公司更不能作为目标倍数。",
        "finalization": "reviewed",
        "inputs": [
            _input("当前总市值", market_cap, "亿元人民币", AS_OF, _artifact_ref(ACTUAL_PATH, f"companies.{ticker}.market_cap"), "financial.db Wind市场快照。", input_type="direct_fact"),
            _input("Wind前瞻市盈率", recon.get("pe_forward"), "倍", AS_OF, _artifact_ref(RECON_PATH, f"companies.{ticker}.pe_forward"), "冻结后外部对账字段。", input_type="direct_fact"),
        ],
        "outputs": implied_outputs, "reconciliations": [],
    }
    observations: list[dict[str, Any]] = []
    if recon.get("status") == "usable":
        observations.append(_observation(
            "pe_forward", recon["pe_forward"], "倍", "consensus", "wind",
            recon.get("raw_feature_name") or "Wind WSS.pe_fy1", "pe_forward_reconciliation",
            frequency="snapshot",
        ))
        observations.append(_observation(
            "net_income", implied_profit, "亿元人民币", "implied", "internal_model",
            "market_cap/pe_forward", "pe_forward_reconciliation", year=2026,
            scenario="wind_pe_forward_implied", model_key=implied_key,
            formula="当前总市值÷Wind前瞻市盈率",
            input_refs=[_artifact_ref(RECON_PATH, f"companies.{ticker}.market_implied_forward_profit_100m_cny")],
        ))
    return [valuation_model, implied_model], observations


def build_export() -> dict[str, Any]:
    for path in (ACTUAL_PATH, MODEL_PATH, RECON_PATH):
        if not path.is_file():
            raise FileNotFoundError(f"missing prerequisite: {path}")
    actual = _read(ACTUAL_PATH)
    model = _read(MODEL_PATH)
    recon = _read(RECON_PATH)
    if recon["independent_model_sha256"] != _sha(MODEL_PATH):
        raise ValueError("reconciliation is not bound to current independent model")
    companies = []
    for ticker, company in model["companies"].items():
        rec = recon["companies"][ticker]
        financial_model, internal_observations = _financial_model(ticker, company, rec)
        valuation_models, implied_observations = _valuation_models(ticker, company, rec)
        snapshots = [
            {
                "key": "actual_market_snapshot", "provider": "wind", "source_channel": "structured_api",
                "source_ref": f"{RUN_REF}:actual_market:{ticker}",
                "title": f"{ticker} financial.db既有Wind实际与市场窄快照",
                "publisher": "Wind内网代理（financial.db既有记录）", "as_of_date": AS_OF,
                "fetched_at": None, "content_hash": _sha(ACTUAL_PATH), "raw_snapshot_path": _rel(ACTUAL_PATH),
                "metadata": {"read_only": True, "external_consensus_excluded_at_freeze": True},
            },
            {
                "key": "independent_model", "provider": "internal_model", "source_channel": "internal_calculation",
                "source_ref": f"{RUN_REF}:independent:{ticker}",
                "title": f"{ticker} Run16八家公司补充独立模型",
                "publisher": "Industry Demo内部研究模型", "as_of_date": AS_OF,
                "fetched_at": None, "content_hash": _sha(MODEL_PATH), "raw_snapshot_path": _rel(MODEL_PATH),
                "metadata": {"independent_before_pe_forward": True, "supplemental_only": True},
            },
            {
                "key": "pe_forward_reconciliation", "provider": "wind", "source_channel": "structured_api",
                "source_ref": f"{RUN_REF}:pe_forward:{ticker}",
                "title": f"{ticker} 冻结后Wind前瞻市盈率对账",
                "publisher": "Wind内网代理（financial.db既有记录）", "as_of_date": AS_OF,
                "fetched_at": None, "content_hash": _sha(RECON_PATH), "raw_snapshot_path": _rel(RECON_PATH),
                "metadata": {"sequence_control": "after independent model freeze"},
            },
            {
                "key": "run16_evidence", "provider": "opportunity_lens", "source_channel": "report",
                "source_ref": f"{RUN_REF}:run16_evidence:{ticker}",
                "title": f"{ticker} Run16既有合同、客户价值与业务边界证据",
                "publisher": "Industry Demo Opportunity Lens", "as_of_date": AS_OF,
                "fetched_at": None, "content_hash": _sha(PACK_PATH), "raw_snapshot_path": _rel(PACK_PATH),
                "metadata": {"source_refs": company["evidence_refs"]},
            },
        ]
        companies.append({
            "research_company_id": int(company["company_id"]),
            "security": {
                "canonical_name": company["name"], "ticker": ticker,
                "market": ticker.split(".")[-1], "listing_status": "listed",
                "reporting_currency": "CNY", "identity_status": "verified",
            },
            "source_snapshots": snapshots,
            "model_runs": [financial_model, *valuation_models],
            "observations": [*internal_observations, *implied_observations],
        })
    payload = {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "research_run_ref": RUN_REF,
        "as_of_date": AS_OF,
        "source_artifacts": [
            {"path": _rel(path), "sha256": _sha(path)}
            for path in (ACTUAL_PATH, MODEL_PATH, RECON_PATH, PACK_PATH)
        ],
        "companies": companies,
    }
    _write(EXPORT_PATH, payload)
    validation = validate_export(payload, export_path=EXPORT_PATH)
    verification = verify_all(payload, actual, model, recon, validation)
    _write(VERIFY_PATH, verification)
    return {
        "stage": "export", "path": str(EXPORT_PATH), "sha256": _sha(EXPORT_PATH),
        "verification_path": str(VERIFY_PATH), "verification_sha256": _sha(VERIFY_PATH),
        "companies": len(companies), "model_runs": sum(len(c["model_runs"]) for c in companies),
        "checks": verification["checks_total"], "status": verification["status"],
    }


def verify_all(export: dict[str, Any], actual: dict[str, Any], model: dict[str, Any], recon: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    check(len(export["companies"]) == 8, "export company count must be 8")
    check(sum(len(c["model_runs"]) for c in export["companies"]) == 24, "each company must have 3 model runs")
    check(validation["company_count"] == 8, "validator company count")
    check(recon["independent_model_sha256"] == _sha(MODEL_PATH), "reconciliation hash chain")
    check(actual["read_contract"]["external_consensus_excluded"] is True, "freeze excludes external consensus")
    model_text = MODEL_PATH.read_text(encoding="utf-8")
    check('"pe_forward"' not in model_text, "independent model must not contain pe_forward key")
    for path_text, before_hash in actual["protected_artifacts_before"].items():
        path = ROOT / path_text
        check(path.is_file() and _sha(path) == before_hash, f"protected artifact changed: {path_text}")
    required_framework = {"applicability", "cycle_sensitivity", "asset_intensity", "basis", "price_exposure", "profit_driver", "tags"}
    buy_texts: set[str] = set()
    sell_texts: set[str] = set()
    for ticker, company in model["companies"].items():
        check(required_framework <= set(company["pb_framework"]), f"{ticker} pb_framework incomplete")
        check(len(company["pb_framework"].get("tags") or []) >= 3, f"{ticker} pb_framework tags")
        for scenario in SCENARIOS:
            previous_revenue = company["baseline"]["revenue_2025"]
            previous_equity = company["baseline"]["parent_equity_proxy"]
            for year in YEARS:
                row = company["scenarios"][scenario][str(year)]
                expected_revenue = previous_revenue * (1 + row["revenue_growth_pct"] / 100)
                expected_profit = row["revenue_100m_cny"] * row["net_margin_pct"] / 100
                expected_ocf = row["revenue_100m_cny"] * row["ocf_margin_pct"] / 100
                expected_capex = row["revenue_100m_cny"] * row["capex_margin_pct"] / 100
                expected_fcf = row["ocf_100m_cny"] - row["capex_100m_cny"]
                expected_equity = previous_equity + row["parent_net_income_100m_cny"]
                check(abs(row["revenue_100m_cny"] - expected_revenue) < 1e-5, f"{ticker} {scenario} {year} revenue")
                check(abs(row["parent_net_income_100m_cny"] - expected_profit) < 1e-5, f"{ticker} {scenario} {year} profit")
                check(abs(row["ocf_100m_cny"] - expected_ocf) < 1e-5, f"{ticker} {scenario} {year} ocf")
                check(abs(row["capex_100m_cny"] - expected_capex) < 1e-5, f"{ticker} {scenario} {year} capex")
                check(abs(row["fcf_100m_cny"] - expected_fcf) < 1e-5, f"{ticker} {scenario} {year} fcf")
                check(abs(row["ending_parent_equity_proxy_100m_cny"] - expected_equity) < 1e-5, f"{ticker} {scenario} {year} equity")
                previous_revenue = row["revenue_100m_cny"]
                previous_equity = row["ending_parent_equity_proxy_100m_cny"]
        rec = recon["companies"][ticker]
        if rec.get("status") == "usable":
            expected = company["baseline"]["market_cap_100m_cny"] / rec["pe_forward"]
            check(abs(rec["market_implied_forward_profit_100m_cny"] - expected) < 1e-5, f"{ticker} implied profit")
        export_company = next(c for c in export["companies"] if c["security"]["ticker"] == ticker)
        for exported_model in export_company["model_runs"]:
            for output in exported_model["outputs"]:
                value = _finite(output.get("value_num"))
                low = _finite(output.get("range_low"))
                high = _finite(output.get("range_high"))
                if low is not None and high is not None:
                    check(low <= high, f"{ticker} {output['output_name']} range order")
                    if value is not None:
                        check(low - 1e-8 <= value <= high + 1e-8, f"{ticker} {output['output_name']} base inside range")
        valuation = next(m for m in export_company["model_runs"] if m["run_key"].endswith("valuation_diagnostic:v1"))
        check(required_framework <= set(valuation["assumptions"]["pb_framework"]), f"{ticker} exported framework")
        check(bool(valuation["assumptions"].get("company_detail_summary")), f"{ticker} company detail summary")
        summary = valuation["assumptions"]["company_detail_summary"]
        buy_texts.add(str(summary.get("buy_point_analysis") or ""))
        sell_texts.add(str(summary.get("sell_point_analysis") or ""))
        pressure_outputs = [o for o in valuation["outputs"] if o["output_name"] == "当前PB反向要求的ROE（仅作压力诊断）"]
        check(len(pressure_outputs) == 1, f"{ticker} PB reverse-pressure label")
        check("不是可持续ROE预测" in pressure_outputs[0]["conclusion"], f"{ticker} PB reverse-pressure warning")
        if company["classification"] not in {"stable_profit", "profit_recovery"}:
            check("not_applicable_for_target_price" == company["valuation_applicability"]["forward_pe"], f"{ticker} loss PE gate")
    check(len(buy_texts) == 8, "company-specific buy triggers must be unique")
    check(len(sell_texts) == 8, "company-specific sell triggers must be unique")
    status = "PASS" if not failures else "FAIL"
    payload = {
        "schema_version": "run16.supplemental_recomputation_verification.v1",
        "status": status,
        "as_of_date": AS_OF,
        "checks_total": checks,
        "failures": failures,
        "hashes": {
            "actual": _sha(ACTUAL_PATH), "independent_model": _sha(MODEL_PATH),
            "reconciliation": _sha(RECON_PATH), "export": _sha(EXPORT_PATH),
        },
        "scope_assertions": {
            "run16_main_pack_unchanged": True,
            "run16_existing_18_company_model_unchanged": True,
            "run16_existing_18_company_export_unchanged": True,
            "live_financial_db_written": False,
            "supplemental_only": True,
        },
        "validation_summary": validation,
    }
    if failures:
        raise ValueError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("freeze", "reconcile", "export", "all"), default="all")
    args = parser.parse_args()
    results = []
    if args.stage in {"freeze", "all"}:
        results.append(freeze())
    if args.stage in {"reconcile", "all"}:
        results.append(reconcile())
    if args.stage in {"export", "all"}:
        results.append(build_export())
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
