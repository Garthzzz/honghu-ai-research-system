from __future__ import annotations

"""Build the audited independent-assumption ledger for AI portfolio run16.

This file deliberately contains only researcher judgements made before reading
Wind consensus.  It expands a compact, company-specific table into the fully
annotated input contract consumed by ``run16_financial_portfolio_model``.
"""

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-07-30"
YEARS = ("2026", "2027", "2028")
SCENARIOS = ("downside", "base", "upside")


def _triplet(down: list[float], base: list[float], up: list[float]) -> dict[str, dict[str, float]]:
    if not all(len(values) == 3 for values in (down, base, up)):
        raise ValueError("每个三情景序列必须各含FY2026—FY2028三个值")
    return {
        scenario: dict(zip(YEARS, values))
        for scenario, values in zip(SCENARIOS, (down, base, up))
    }


def _input(value: float, unit: str, source: str, rationale: str) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "basis_type": "internal_estimate",
        "as_of": AS_OF,
        "source_ref": source,
        "rationale": rationale,
    }


def _series(values: dict[str, dict[str, float]], unit: str, source: str, rationale: str) -> dict[str, Any]:
    return {
        "values": values,
        "unit": unit,
        "basis_type": "internal_estimate",
        "as_of": AS_OF,
        "source_ref": source,
        "rationale": rationale,
    }


def _zero_series(source: str, label: str) -> dict[str, Any]:
    return _series(
        _triplet([0, 0, 0], [0, 0, 0], [0, 0, 0]),
        "亿元人民币",
        source,
        f"截至研究日没有把未公告的{label}当作基准事实；发生已公告事项时应单独更新。",
    )


COMPANIES: list[dict[str, Any]] = [
    {
        "ticker": "688111.SH", "name": "金山办公", "company_id": 668,
        "mechanism": "个人订阅、机构授权与WPS 365构成收入底盘，AI主要通过付费转化、客单价、留存和推理成本改变增长与利润率。",
        "quality": "high", "direction": "办公与协作智能", "scopes": ["applications"],
        "source": "Wind FY2021—FY2025/2026Q1实际；AI应用证据C01、C02；公司2026Q1公告的剔除投资收益口径",
        "rev": ([14, 12, 10], [22, 20, 18], [29, 27, 23]),
        "gm": ([83, 82, 82], [86, 86, 86], [87, 87, 87]),
        "nm": ([25, 25, 26], [31.5, 32, 32.5], [34, 35, 36]),
        "ocf": ([31, 32, 33], [41, 42, 42], [45, 46, 46]),
        "capex": ([3.5, 3.5, 3], [2.5, 2.5, 2.5], [2, 2, 2]),
        "assets": ([5, 5, 5], [9, 9, 8], [13, 12, 10]), "payout": ([30]*3, [35]*3, [40]*3),
        "pe": (32, 42), "ke": (8.5, 10.5), "g": (2, 3), "pb": None,
        "scores": (88, 88, 90, 38, 38),
        "normalization": {
            "parent_net_income_100m_cny": (18.0252, "2025年账面归母净利润", "采用公司2025年扣非归母净利润作为年度主业基线，差额不进入经常性盈利外推。"),
            "q1_2026_parent_net_income_100m_cny": (5.80, "2026Q1账面归母净利润及扣非净利润", "公司披露剔除基金投资收益后的归母净利润约5.80亿元；该口径更接近办公主业盈利。"),
        },
    },
    {
        "ticker": "688615.SH", "name": "合合信息", "company_id": 669,
        "mechanism": "智能文字识别、文档解析和商业数据服务按用户、调用量与订阅单价变现，数据与场景积累决定续费和毛利。",
        "quality": "medium", "direction": "文档解析与商业数据", "scopes": ["applications"],
        "source": "Wind FY2021—FY2025/2026Q1实际；AI应用证据C03、C04",
        "rev": ([15, 14, 12], [25, 22, 19], [32, 28, 24]),
        "gm": ([83, 83, 83], [86, 86.5, 87], [88, 88, 88]),
        "nm": ([20, 21, 22], [25.5, 26, 27], [29, 30, 31]),
        "ocf": ([25, 26, 27], [33, 34, 35], [38, 39, 40]),
        "capex": ([7, 6, 5], [5, 4.5, 4], [4, 3.5, 3]),
        "assets": ([8, 7, 6], [13, 12, 10], [18, 16, 14]), "payout": ([20]*3, [30]*3, [35]*3),
        "pe": (28, 38), "ke": (9, 11), "g": (2, 3), "pb": None,
        "scores": (82, 82, 80, 55, 42),
    },
    {
        "ticker": "300033.SZ", "name": "同花顺", "company_id": 670,
        "mechanism": "金融信息服务、广告和交易活跃度形成周期底盘，AI问答与投研工具提高用户价值，但收入仍受资本市场成交和客户预算影响。",
        "quality": "high", "direction": "金融知识与决策", "scopes": ["applications"],
        "source": "Wind FY2021—FY2025/2026Q1实际；AI应用证据C05、C06",
        "rev": ([10, 0, -5], [28, 15, 10], [40, 25, 18]),
        "gm": ([86, 85, 85], [89, 89, 89], [91, 91, 91]),
        "nm": ([40, 38, 36], [50, 48, 47], [55, 54, 52]),
        "ocf": ([42, 40, 38], [56, 54, 52], [62, 61, 59]),
        "capex": ([3, 3, 3], [2.5, 2.5, 2.5], [2, 2, 2]),
        "assets": ([2, 1, 1], [8, 7, 6], [14, 12, 10]), "payout": ([35]*3, [45]*3, [50]*3),
        "pe": (28, 36), "ke": (9, 11), "g": (1.5, 2.5), "pb": None,
        "scores": (78, 88, 82, 35, 55),
    },
    {
        "ticker": "002230.SZ", "name": "科大讯飞", "company_id": 94,
        "mechanism": "教育、医疗、政企和消费者硬件项目收入由订单、交付与回款驱动，模型调用和销售投入决定AI增长能否转成净利润和现金流。",
        "quality": "medium", "direction": "教育医疗与公共服务", "scopes": ["applications"],
        "source": "Wind FY2021—FY2025/2026Q1实际；AI应用证据C07、C08",
        "rev": ([8, 8, 6], [15, 17, 16], [22, 25, 22]),
        "gm": ([37, 37, 38], [40, 41, 42], [43, 44, 45]),
        "nm": ([1, 1.5, 2], [3.5, 4.5, 5.5], [6, 7.5, 9]),
        "ocf": ([6, 7, 8], [11, 12, 13], [15, 16, 17]),
        "capex": ([12, 11, 10], [10, 9, 8], [9, 8, 7]),
        "assets": ([8, 7, 6], [13, 12, 10], [18, 16, 14]), "payout": ([0]*3, [10]*3, [15]*3),
        "pe": (40, 55), "ke": (10, 12), "g": (2, 3), "pb": None,
        "scores": (85, 52, 75, 22, 72),
    },
    {
        "ticker": "300378.SZ", "name": "鼎捷数智", "company_id": 671,
        "mechanism": "制造业软件实施、订阅和工业AI项目按签约、交付、续费与人均产出变现，AI能否减少实施成本比概念曝光更重要。",
        "quality": "medium", "direction": "企业管理与工业流程", "scopes": ["applications"],
        "source": "Wind FY2021—FY2025/2026Q1实际；AI应用证据C09、C10",
        "rev": ([2, 5, 6], [9, 13, 15], [15, 20, 22]),
        "gm": ([54, 54, 55], [58, 59, 60], [62, 63, 64]),
        "nm": ([3, 4, 5], [7, 7.8, 8.5], [10, 11, 12]),
        "ocf": ([6, 7, 8], [10, 11, 13], [15, 16, 17]),
        "capex": ([9, 8, 7], [7, 6, 5], [5, 4, 4]),
        "assets": ([4, 4, 4], [9, 9, 9], [14, 14, 13]), "payout": ([10]*3, [20]*3, [25]*3),
        "pe": (30, 40), "ke": (10, 12), "g": (1.5, 2.5), "pb": None,
        "scores": (72, 65, 65, 60, 50),
    },
    {
        "ticker": "300454.SZ", "name": "深信服", "company_id": 672,
        "mechanism": "网络安全、云化和IT运营产品由订阅、项目与渠道回款驱动，AI提高检测与运维价值，同时推理资源和获客投入压制利润。",
        "quality": "medium", "direction": "网络安全与IT运营", "scopes": ["applications"],
        "source": "Wind FY2021—FY2025/2026Q1实际；AI应用证据C11、C12",
        "rev": ([10, 8, 6], [18, 15, 13], [25, 22, 18]),
        "gm": ([56, 56, 57], [60, 60, 61], [63, 64, 64]),
        "nm": ([1, 2, 3], [5.5, 7, 8.5], [9, 11, 13]),
        "ocf": ([8, 9, 10], [14, 15, 16], [19, 20, 21]),
        "capex": ([6, 5.5, 5], [4, 4, 3.5], [3, 3, 3]),
        "assets": ([5, 5, 5], [10, 9, 8], [15, 14, 12]), "payout": ([0]*3, [10]*3, [15]*3),
        "pe": (40, 55), "ke": (10, 12), "g": (1.5, 2.5), "pb": None,
        "scores": (75, 67, 70, 25, 65),
    },
    {
        "ticker": "601138.SH", "name": "工业富联", "company_id": 284,
        "mechanism": "AI服务器和网络设备以出货量、单机价值量、客户份额和制造效率驱动收入，低毛利制造属性使营运资金和资本开支决定现金质量。",
        "quality": "high", "direction": "AI服务器制造", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W027及海外云厂商资本开支证据FC-W012—FC-W015",
        "rev": ([25, 10, 4], [45, 25, 16], [60, 36, 23]),
        "gm": ([6.2, 6.2, 6.2], [7.2, 7.4, 7.5], [8, 8.2, 8.3]),
        "nm": ([3.2, 3.2, 3.2], [4.2, 4.3, 4.4], [4.8, 5, 5.1]),
        "ocf": ([2.5, 3, 3.2], [4, 4.5, 4.8], [5.5, 5.8, 6]),
        "capex": ([2.8, 2.5, 2.3], [2.2, 2, 1.8], [2, 1.8, 1.6]),
        "assets": ([10, 7, 5], [20, 14, 10], [27, 20, 14]), "payout": ([30]*3, [40]*3, [50]*3),
        "pe": (16, 22), "ke": (9, 11), "g": (1.5, 2.5), "pb": (1.2, 2.0, 5),
        "scores": (90, 78, 90, 75, 50),
    },
    {
        "ticker": "300308.SZ", "name": "中际旭创", "company_id": 1,
        "mechanism": "高速光模块收入由AI集群端口数、产品代际、份额与ASP共同决定，良率、光芯片和客户集中度决定利润与现金流。",
        "quality": "high", "direction": "高速光互连", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W028、FC-W001、FC-W003、FC-W007",
        "rev": ([45, 8, 0], [80, 30, 18], [99, 50, 30]),
        "gm": ([36, 34, 32], [44, 42, 40], [48, 47, 45]),
        "nm": ([23, 21, 19], [31.5, 30.5, 29.5], [35, 35, 34]),
        "ocf": ([18, 18, 17], [26, 25, 24], [31, 30, 29]),
        "capex": ([12, 10, 8], [9, 7, 6], [8, 6, 5]),
        "assets": ([25, 13, 8], [42, 25, 17], [55, 36, 25]), "payout": ([10]*3, [20]*3, [25]*3),
        "pe": (25, 33), "ke": (10, 12), "g": (1.5, 2.5), "pb": None,
        "scores": (95, 88, 92, 50, 62),
    },
    {
        "ticker": "002463.SZ", "name": "沪电股份", "company_id": 326,
        "mechanism": "高层数高速PCB按AI服务器、交换机和路由器板卡面积、层数、ASP、良率与产能利用率传导至收入和毛利。",
        "quality": "high", "direction": "高端PCB", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W029、FC-W007、FC-W009",
        "rev": ([25, 10, 5], [50, 32, 20], [65, 45, 30]),
        "gm": ([29, 28, 27], [37, 38, 37], [41, 42, 41]),
        "nm": ([15, 14, 13], [21, 21.5, 21], [24, 25, 24.5]),
        "ocf": ([13, 13, 12], [20, 20, 19], [24, 24, 23]),
        "capex": ([22, 16, 10], [18, 12, 8], [16, 10, 7]),
        "assets": ([18, 12, 8], [30, 22, 15], [40, 30, 22]), "payout": ([20]*3, [30]*3, [35]*3),
        "pe": (22, 30), "ke": (9.5, 11.5), "g": (1.5, 2.5), "pb": (1.5, 2.5, 5),
        "scores": (92, 90, 90, 62, 50),
    },
    {
        "ticker": "002371.SZ", "name": "北方华创", "company_id": 424,
        "mechanism": "半导体设备由晶圆厂资本开支、国产验证、产品覆盖、订单交付和服务收入驱动，存货、验收与研发投入决定现金兑现。",
        "quality": "high", "direction": "半导体设备", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W030、FC-W010、FC-W011",
        "rev": ([15, 12, 10], [26, 24, 20], [35, 32, 27]),
        "gm": ([37, 37, 37], [41, 42, 43], [45, 46, 47]),
        "nm": ([11, 11.5, 12], [15, 16, 17], [18, 19, 20]),
        "ocf": ([3, 4, 5], [8, 9, 10], [12, 13, 14]),
        "capex": ([8, 7, 6], [6, 5.5, 5], [5, 4.5, 4]),
        "assets": ([14, 13, 12], [22, 21, 18], [30, 28, 24]), "payout": ([10]*3, [15]*3, [20]*3),
        "pe": (35, 45), "ke": (9.5, 11.5), "g": (2, 3), "pb": (1.8, 3.0, 6),
        "scores": (88, 88, 91, 35, 55),
    },
    {
        "ticker": "688008.SH", "name": "澜起科技", "company_id": 97,
        "mechanism": "内存接口与互连芯片按服务器平台渗透、DDR代际、单机颗数和授权壁垒变现，高毛利但受内存与服务器周期影响。",
        "quality": "high", "direction": "内存互连", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W031、FC-W004—FC-W006",
        "rev": ([12, 15, 12], [28, 30, 25], [40, 42, 35]),
        "gm": ([57, 56, 56], [64, 65, 66], [68, 69, 70]),
        "nm": ([30, 30, 30], [40, 41, 42], [46, 47, 48]),
        "ocf": ([27, 28, 29], [35, 37, 38], [42, 44, 45]),
        "capex": ([8, 7, 6], [6, 5, 5], [5, 4, 4]),
        "assets": ([8, 9, 8], [14, 15, 13], [20, 21, 18]), "payout": ([20]*3, [30]*3, [35]*3),
        "pe": (40, 55), "ke": (9.5, 11.5), "g": (2, 3), "pb": None,
        "scores": (90, 90, 88, 35, 48),
    },
    {
        "ticker": "688041.SH", "name": "海光信息", "company_id": 330,
        "mechanism": "国产CPU/DCU收入由可供货产品、软件生态、整机导入和政策需求驱动，估值依赖高增速持续和研发资本效率。",
        "quality": "high", "direction": "国产计算芯片", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W026、FC-W022、FC-W024",
        "rev": ([25, 20, 15], [48, 38, 30], [62, 52, 42]),
        "gm": ([50, 49, 48], [56, 57, 57], [61, 62, 62]),
        "nm": ([13, 14, 15], [18.5, 20, 21.5], [24, 26, 28]),
        "ocf": ([8, 9, 10], [15, 17, 18], [21, 23, 24]),
        "capex": ([13, 12, 10], [10, 9, 8], [8, 7, 6]),
        "assets": ([20, 18, 15], [34, 30, 25], [45, 40, 34]), "payout": ([0]*3, [10]*3, [15]*3),
        "pe": (50, 65), "ke": (10.5, 12.5), "g": (2, 3), "pb": None,
        "scores": (93, 82, 86, 12, 68),
    },
    {
        "ticker": "002837.SZ", "name": "英维克", "company_id": 231,
        "mechanism": "数据中心温控收入由机柜功率密度、液冷渗透、项目交付和服务决定，项目结构、原材料与费用投放决定净利率。",
        "quality": "medium", "direction": "液冷与热管理", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W032、FC-W016—FC-W021",
        "rev": ([18, 15, 12], [35, 30, 25], [48, 42, 34]),
        "gm": ([24, 24, 24], [28, 29, 30], [32, 33, 34]),
        "nm": ([5, 5.5, 6], [8, 9.5, 10], [11, 12, 13]),
        "ocf": ([4, 5, 6], [8, 9, 10], [13, 14, 15]),
        "capex": ([9, 8, 7], [7, 6, 5.5], [6, 5, 5]),
        "assets": ([12, 10, 8], [24, 20, 17], [34, 29, 24]), "payout": ([10]*3, [20]*3, [25]*3),
        "pe": (32, 42), "ke": (10, 12), "g": (1.5, 2.5), "pb": None,
        "scores": (86, 65, 75, 48, 62),
    },
    {
        "ticker": "002364.SZ", "name": "中恒电气", "company_id": 673,
        "mechanism": "高压直流与数据中心电源由机房建设、功率密度、项目验证和订单交付驱动，小基数使收入波动和费用吸收风险更高。",
        "quality": "medium", "direction": "数据中心供电", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W036、FC-W016、FC-W019—FC-W023",
        "rev": ([5, 8, 8], [20, 30, 28], [35, 45, 38]),
        "gm": ([20, 20, 21], [25, 26, 27], [29, 30, 31]),
        "nm": ([3, 3.5, 4], [7, 8.5, 9.5], [11, 13, 14]),
        "ocf": ([5, 6, 7], [12, 13, 14], [17, 18, 19]),
        "capex": ([5, 5, 5], [3, 3, 3], [3, 3, 3]),
        "assets": ([5, 6, 6], [14, 18, 17], [23, 28, 24]), "payout": ([10]*3, [20]*3, [25]*3),
        "pe": (35, 48), "ke": (10.5, 12.5), "g": (1.5, 2.5), "pb": None,
        "scores": (82, 58, 70, 38, 67),
    },
    {
        "ticker": "300442.SZ", "name": "润泽科技", "company_id": 266,
        "mechanism": "AIDC机柜、上架率和单柜收入驱动经营现金流，扩建资本开支、融资成本、客户集中与投产节奏共同决定自由现金流和估值。",
        "quality": "medium", "direction": "数据中心运营", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W033、FC-W012—FC-W018；公司2025年报扣非归母净利润",
        "rev": ([18, 15, 12], [38, 32, 25], [52, 45, 35]),
        "gm": ([40, 39, 38], [47, 46, 44], [52, 51, 49]),
        "nm": ([25, 24, 23], [35, 34, 32], [40, 39, 37]),
        "ocf": ([35, 36, 37], [48, 48, 47], [55, 55, 54]),
        "capex": ([65, 45, 30], [55, 35, 22], [45, 28, 18]),
        "assets": ([24, 20, 16], [40, 34, 26], [52, 45, 35]), "payout": ([5]*3, [15]*3, [20]*3),
        "pe": (24, 32), "ke": (10, 12), "g": (1.5, 2.5), "pb": None,
        "scores": (88, 60, 78, 58, 70),
        "normalization": {
            "parent_net_income_100m_cny": (19.0062, "2025年账面归母净利润50.50亿元", "采用年报扣除非经常性损益后的归母净利润19.01亿元作为经营利润基线；资产处置等非经常收益不外推。"),
        },
    },
    {
        "ticker": "600183.SH", "name": "生益科技", "company_id": 325,
        "mechanism": "覆铜板收入由高频高速材料面积、规格升级、ASP、良率与产能利用率驱动，上游铜箔和树脂价格影响利润率。",
        "quality": "high", "direction": "低损耗覆铜板", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W035、FC-W007、FC-W009",
        "rev": ([20, 10, 6], [40, 28, 20], [55, 40, 30]),
        "gm": ([22, 21, 20], [28, 29, 28], [32, 33, 32]),
        "nm": ([9, 8.5, 8], [14.5, 15.5, 15], [17, 18, 17.5]),
        "ocf": ([12, 11, 10], [18, 18, 17], [22, 22, 21]),
        "capex": ([13, 11, 9], [10, 8, 7], [8, 7, 6]),
        "assets": ([12, 9, 7], [24, 18, 14], [32, 25, 20]), "payout": ([25]*3, [35]*3, [40]*3),
        "pe": (24, 32), "ke": (9.5, 11.5), "g": (1.5, 2.5), "pb": (1.2, 2.2, 5),
        "scores": (84, 78, 83, 52, 55),
    },
    {
        "ticker": "002475.SZ", "name": "立讯精密", "company_id": 14,
        "mechanism": "消费电子底盘、AI高速铜连接和通信组件按客户份额、单机价值与制造效率共同驱动，业务多元化降低单一AI节点暴露。",
        "quality": "high", "direction": "高速铜互连", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W034、FC-W007—FC-W009",
        "rev": ([15, 10, 8], [28, 20, 16], [36, 28, 22]),
        "gm": ([10, 10, 10], [12, 12.2, 12.5], [14, 14.5, 15]),
        "nm": ([4.2, 4.2, 4.3], [5.5, 5.8, 6], [6.5, 7, 7.3]),
        "ocf": ([4, 4.5, 4.8], [6, 6.5, 6.8], [8, 8.5, 9]),
        "capex": ([7, 7, 6.5], [6, 5.5, 5], [5, 4.5, 4]),
        "assets": ([12, 9, 7], [21, 16, 13], [28, 22, 17]), "payout": ([20]*3, [30]*3, [35]*3),
        "pe": (18, 24), "ke": (9, 11), "g": (1.5, 2.5), "pb": (1.2, 2.0, 5),
        "scores": (85, 82, 85, 75, 48),
    },
    {
        "ticker": "300124.SZ", "name": "汇川技术", "company_id": 279,
        "mechanism": "工业自动化、新能源汽车和机器人产品由下游设备投资、份额、单价与规模制造驱动，AI受益更多体现为工业控制和生产率而非纯算力。",
        "quality": "high", "direction": "工业智能与机器人", "scopes": ["full_chain"],
        "source": "Wind FY2021—FY2025/2026Q1实际；全产业链证据FC-W038、FC-W025",
        "rev": ([8, 8, 8], [18, 20, 18], [26, 28, 25]),
        "gm": ([25, 25, 25], [29, 29.5, 30], [33, 34, 34]),
        "nm": ([8, 8.5, 9], [11.5, 12, 12.5], [14, 15, 15.5]),
        "ocf": ([8, 9, 9], [13, 14, 14], [17, 18, 18]),
        "capex": ([9, 8, 7], [7, 6.5, 6], [6, 5.5, 5]),
        "assets": ([8, 8, 8], [15, 16, 15], [22, 23, 21]), "payout": ([20]*3, [30]*3, [35]*3),
        "pe": (24, 32), "ke": (9, 11), "g": (1.5, 2.5), "pb": (1.3, 2.2, 5),
        "scores": (80, 84, 82, 68, 45),
    },
]


def _forecast_assumptions(row: dict[str, Any]) -> dict[str, Any]:
    source = row["source"]
    return {
        "revenue_growth_pct": _series(_triplet(*row["rev"]), "%", source, "以FY2025收入、2026Q1增速和产品需求/份额传导形成三情景，不直接复制外部盈利预测。"),
        "gross_margin_pct": _series(_triplet(*row["gm"]), "%", source, "以历史毛利率、产品结构、价格竞争和规模效率形成区间。"),
        "parent_net_margin_pct": _series(_triplet(*row["nm"]), "%", source, "从毛利率扣除研发、销售管理、财务、税费和少数股东影响后估计归母净利率。"),
        "ocf_margin_pct": _series(_triplet(*row["ocf"]), "%", source, "以历史经营现金流、回款、存货和合同负债波动形成现金转换区间。"),
        "capex_margin_pct": _series(_triplet(*row["capex"]), "%", source, "以历史资本开支和未来扩产/研发基础设施需求占收入比例估计。"),
        "total_assets_growth_pct": _series(_triplet(*row["assets"]), "%", source, "使资产扩张与收入、产能和营运资本需求对应，用于ROA和权益桥而非直接拍ROA。"),
        "dividend_payout_pct": _series(_triplet(*row["payout"]), "%", source, "按历史分红能力、成长投入和现金约束形成三情景；不是公司已公告承诺。"),
        "buyback_100m_cny": _zero_series(source, "回购"),
        "other_equity_change_100m_cny": _zero_series(source, "增发、股权激励及其他权益变动"),
    }


def _valuation(row: dict[str, Any]) -> dict[str, Any]:
    source = row["source"]
    pe_low, pe_high = row["pe"]
    ke_low, ke_high = row["ke"]
    g_low, g_high = row["g"]
    pb = row["pb"]
    return {
        "pe": {
            "enabled": True, "role": "核心" if row["quality"] == "high" else "有效参考", "target_year": 2027,
            "multiple_low": _input(pe_low, "倍", source, "下限对应需求降速、利润兑现不足和估值回归。"),
            "multiple_high": _input(pe_high, "倍", source, "上限要求基准收入与利润率兑现，且不采用远期牛市峰值。"),
        },
        "dcf": {
            "enabled": True, "role": "诊断",
            "cost_of_equity_low_pct": _input(ke_low, "%", "中国无风险利率、科技股风险溢价和公司风险研究底稿", "低股权成本对应基本面兑现且风险偏好正常。"),
            "cost_of_equity_high_pct": _input(ke_high, "%", "中国无风险利率、科技股风险溢价和公司风险研究底稿", "高股权成本覆盖执行、政策、周期及客户集中风险。"),
            "terminal_growth_low_pct": _input(g_low, "%", "长期名义经济增长与行业成熟期约束", "下限按成熟期保守名义增长。"),
            "terminal_growth_high_pct": _input(g_high, "%", "长期名义经济增长与行业成熟期约束", "上限不把近三年AI高增外推为永续增长。"),
        },
        "pb_roe": {
            "enabled": True, "role": "诊断", "stable_roe": pb is not None,
            "stability_evidence": (["Wind FY2021—FY2025权益和归母净利润序列为正，业务已形成可复核资本回报底盘；仍只作诊断。"] if pb else []),
            "cost_of_equity_low_pct": _input(ke_low, "%", "公司风险与权益资本成本研究底稿", "与DCF低股权成本同口径。"),
            "cost_of_equity_high_pct": _input(ke_high, "%", "公司风险与权益资本成本研究底稿", "与DCF高股权成本同口径。"),
            "terminal_pb_low": _input(pb[0] if pb else 1.0, "倍", source, "成熟期资本回报和资产质量的保守终端PB。"),
            "terminal_pb_high": _input(pb[1] if pb else 1.0, "倍", source, "仅在ROE稳定性门禁通过时使用的终端PB上限。"),
            "convergence_years": _input(pb[2] if pb else 5, "年", source, "预计异常回报向成熟期收敛的时间，不代表公司指引。"),
        },
        "reverse_pe_year": 2027,
    }


def _normalization(row: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for metric, (value, affected, reason) in row.get("normalization", {}).items():
        output[metric] = {
            **_input(value, "亿元人民币", row["source"], reason),
            "affected_reported_item": affected,
            "adjustment_reason": reason,
        }
    return output


def _portfolio(row: dict[str, Any]) -> dict[str, Any]:
    labels = ("direction_score", "quality_score", "evidence_score", "valuation_score", "risk_score")
    rationales = (
        "方向分综合可服务市场、需求持续性与利润池位置。",
        "质量分综合现金流、竞争壁垒与财务稳健性；公司治理单独核验，不混入本轮量化分数。",
        "证据分综合公告、年报、客户/供应商与独立行业证据密度。",
        "估值分越高代表独立估值相对当前市值越有缓冲，不等同收益预测。",
        "风险分越高代表周期、估值、客户、政策或执行风险越高。",
    )
    payload = {
        "eligible": True, "scopes": row["scopes"], "direction": row["direction"],
    }
    for key, value, rationale in zip(labels, row["scores"], rationales):
        payload[key] = _input(value, "分", row["source"], rationale)
    return payload


def _shock(value: float, unit: str, rationale: str) -> dict[str, Any]:
    return _input(value, unit, "run16反方情景底稿；非外部事实", rationale)


def _shock_set(
    revenue: float, margin: float, ocf: float, capex: float, multiple: float, note: str
) -> dict[str, Any]:
    return {
        "revenue_growth_delta_pp": _shock(revenue, "百分点", f"{note}；收入增速调整。"),
        "parent_net_margin_delta_pp": _shock(margin, "百分点", f"{note}；归母净利率调整。"),
        "ocf_margin_delta_pp": _shock(ocf, "百分点", f"{note}；经营现金流率调整。"),
        "capex_margin_delta_pp": _shock(capex, "百分点", f"{note}；资本开支率调整。"),
        "valuation_multiple_change_pct": _shock(multiple, "%", f"{note}；估值倍数调整。"),
    }


def build() -> dict[str, Any]:
    rows = []
    for row in COMPANIES:
        rows.append({
            "ticker": row["ticker"], "name": row["name"], "company_id": row["company_id"],
            "economic_mechanism": row["mechanism"], "data_quality": row["quality"],
            "normalization_overrides": _normalization(row),
            "forecast_assumptions": _forecast_assumptions(row),
            "valuation_methods": _valuation(row),
            "portfolio": _portfolio(row),
        })
    return {
        "template_only": False,
        "independent_before_consensus": True,
        "as_of_date": AS_OF,
        "companies": rows,
        "portfolio_policies": {
            "concentrated": {
                "min_holdings": 3,
                "max_holdings": 3,
                "max_weight_pct": 35,
                "max_direction_weight_pct": 35,
                "cash_weight_pct": 0,
                "max_pair_correlation": 0.85,
                "min_overlap_days": 120,
                "conviction_theme_by_scope": {
                    "applications": "企业知识工作流",
                    "full_chain": "高速数据搬运",
                },
                "conviction_directions_by_scope": {
                    "applications": ["办公与协作智能", "金融知识与决策", "文档解析与商业数据"],
                    "full_chain": ["高速光互连", "高速铜互连", "内存互连"],
                },
            },
            "balanced": {"min_holdings": 5, "max_holdings": 8, "max_weight_pct": 22, "max_direction_weight_pct": 22, "cash_weight_pct": 0, "max_pair_correlation": 0.88, "min_overlap_days": 120},
            "risk_diversified": {"min_holdings": 6, "max_holdings": 10, "max_weight_pct": 18, "max_direction_weight_pct": 18, "cash_weight_pct": 10, "max_pair_correlation": 0.90, "min_overlap_days": 120},
        },
        "stress_scenarios": [
            {
                "name": "AI应用付费兑现延后",
                "description": "应用部署量增长但付费转化与客单价未同步，推理和销售投入先发生。",
                "direction_shocks": {
                    "default": _shock_set(0, 0, 0, 0, 0, "不属于本压力情景的方向保持基准"),
                    **{direction: _shock_set(-7, -4, -4, 1, -25, "AI付费转化、客单价和回款低于基准") for direction in (
                        "办公与协作智能", "文档解析与商业数据", "金融知识与决策",
                        "教育医疗与公共服务", "企业管理与工业流程", "网络安全与IT运营",
                    )},
                },
            },
            {
                "name": "全球AI资本开支降速",
                "description": "云厂商从建设期进入消化期，服务器、互连、PCB、材料和温控订单同步降速。",
                "direction_shocks": {
                    "default": _shock_set(0, 0, 0, 0, 0, "不属于本压力情景的方向保持基准"),
                    **{direction: _shock_set(-10, -3, -5, 2, -30, "云厂商资本开支和订单从建设期转入消化期") for direction in (
                        "AI服务器制造", "高速光互连", "高端PCB", "半导体设备", "内存互连",
                        "国产计算芯片", "液冷与热管理", "数据中心供电", "数据中心运营",
                        "低损耗覆铜板", "高速铜互连", "工业智能与机器人",
                    )},
                },
            },
            {
                "name": "出口限制与供应瓶颈加严",
                "description": "先进芯片、设备或关键材料许可收紧，同时国产供给替代速度低于预期。",
                "direction_shocks": {
                    "default": _shock_set(0, 0, 0, 0, 0, "不属于本压力情景的方向保持基准"),
                    **{direction: _shock_set(-8, -3, -3, 2, -20, "先进产品许可、关键部件和客户交付受限") for direction in (
                        "AI服务器制造", "高速光互连", "高端PCB", "半导体设备", "内存互连",
                        "国产计算芯片", "低损耗覆铜板", "高速铜互连",
                    )},
                },
            },
            {
                "name": "能源与数据中心审批约束",
                "description": "电力接入、PUE、设备交付或项目审批滞后，机柜投产慢于服务器采购计划。",
                "direction_shocks": {
                    "default": _shock_set(0, 0, 0, 0, 0, "不属于本压力情景的方向保持基准"),
                    **{direction: _shock_set(-6, -2, -4, 3, -18, "电力接入、PUE或项目审批使交付和上架延后") for direction in (
                        "AI服务器制造", "液冷与热管理", "数据中心供电", "数据中心运营",
                    )},
                },
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "company_count": len(payload["companies"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
