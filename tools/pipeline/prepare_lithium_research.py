#!/usr/bin/env python
from __future__ import annotations

"""Prepare the two B-track claim packs, industry shells and decision charts."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .lithium_research_data import (
    CARBONATE_SD_PATH,
    KEY_ARGUMENTS,
    LITHIUM_SD_PATH,
    MODEL_PATH,
    SOURCE_SPECS,
    build_data_points,
)


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
CACHE = ROOT / "cache" / "lithium_research"
CLAIMS_DIR = ROOT / "cache" / "claims"
VIS_DIR = ROOT / "tools" / "viewer" / "static" / "generated" / "lithium"
AS_OF_DATE = "2026-07-27"
PARENT = "有色金属"
RUNS = {
    "锂": "lithium_b_20260727",
    "碳酸锂": "lithium_carbonate_b_20260727",
}


def _file_sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_industries(db_path: Path) -> dict[str, int]:
    """Ensure two independently browsable top-level industry records.

    Args:
        db_path: Research SQLite path. This function writes only the industry
            identity rows for the two completed libraries.

    Returns:
        Mapping from industry name to integer ``industry.id``.

    An empty parent-level "有色金属" shell is misleading in the public Viewer.
    The two libraries therefore stay top-level until that parent has its own
    complete research package.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        result = {}
        dynamics = {
            "锂": (
                "全球锂需求继续由动力与储能推动；中期不是地质资源不足，而是新矿、"
                "盐湖、回收和加工项目的有效投产速度能否跟上需求。"
            ),
            "碳酸锂": (
                "2026年中国产品市场由库存去化转向紧平衡，价格取决于产量、进口、"
                "库存和储能需求的共同变化，年度缺口不等于现货单边上涨。"
            ),
        }
        for name in RUNS:
            row = conn.execute("SELECT id FROM industry WHERE name=?", (name,)).fetchone()
            if row:
                industry_id = int(row[0])
                conn.execute(
                    """UPDATE industry SET parent_id=NULL,level=1,tier=1,status='深度跟踪',
                              core_dynamic=?,last_updated=? WHERE id=?""",
                    (dynamics[name], AS_OF_DATE, industry_id),
                )
            else:
                industry_id = int(
                    conn.execute(
                        """INSERT INTO industry(
                             name,parent_id,level,tier,status,core_dynamic,last_updated
                           ) VALUES(?,?,?,?,?,?,?)""",
                        (
                            name,
                            None,
                            1,
                            1,
                            "深度跟踪",
                            dynamics[name],
                            AS_OF_DATE,
                        ),
                    ).lastrowid
                )
            result[name] = industry_id
        conn.commit()
        return result
    finally:
        conn.close()


def _source_payload(spec: dict[str, Any]) -> dict[str, Any]:
    row = {key: value for key, value in spec.items() if value is not None}
    file = row.pop("source_file", None)
    if file:
        row["source_file"] = f"papers/锂/{file}"
    row["value_layer"] = "双层" if int(row.get("quality_tier", 3)) <= 2 else "信息流"
    row["source_subtype"] = (
        "company_filing"
        if row.get("is_primary_source") and file and "年度报告" in row.get("title", "")
        else "official_web"
        if row.get("is_primary_source")
        else "research_report"
    )
    row["is_forward_looking"] = int(
        row["source_ref"]
        in {
            "iea_gcm_2026",
            "australia_req_202606",
            "dongwu_carbonate_20260226",
            "zheshang_lithium_20260614",
            "dongfang_lithium_20260222",
            "dongbei_carbonate_20260519",
        }
    )
    row["fetch_timestamp"] = f"{AS_OF_DATE}T20:00:00+08:00"
    row["independence_basis"] = row.pop("independence_rationale")
    row["note"] = row["independence_basis"]
    return row


def write_claims(industry: str) -> Path:
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    rows = build_data_points(industry)
    used_refs = {row["source_ref"] for row in rows}
    used_refs.update(
        str(row.get("source_ref") or "").strip()
        for row in KEY_ARGUMENTS[industry]
        if str(row.get("source_ref") or "").strip()
    )
    sources = [spec for spec in SOURCE_SPECS if spec["source_ref"] in used_refs]
    identities = {
        (
            row["source_ref"],
            row.get("company"),
            row["metric"],
            row["unit"],
            row.get("scope_key"),
        )
        for row in rows
    }
    payload = {
        "meta": {
            "industry": industry,
            "run_tag": RUNS[industry],
            "research_question": (
                "未来三至五年全球锂资源的有效供需、项目投产、国家政策和企业竞争如何演变？"
                if industry == "锂"
                else "未来三至五年中国与全球碳酸锂产品供需、库存、价格和成本如何演变，并怎样传导到主要公司的利润、现金流与估值？"
            ),
            "scope": {
                "product": (
                    "锂矿、盐湖卤水、锂精矿、回收与折合LCE"
                    if industry == "锂"
                    else "电池级与工业级碳酸锂、进口、库存、下游需求及与氢氧化锂的转换边界"
                ),
                "market_cutoff": AS_OF_DATE,
                "database_boundary": "供应商财务、行情、一致预期和内部模型明细只存在financial.db。",
            },
            "evidence_accounting": {
                "observation_count": len(rows),
                "parallel_research_fact_count": len(identities),
                "used_source_independent_evidence_group_count": len(
                    {spec["independence_key"] for spec in sources}
                ),
                "note": "同源同主体同指标跨期序列合并为一个平行研究事实。",
            },
        },
        "sources": [_source_payload(spec) for spec in sources],
        "data_points": rows,
        "key_arguments": KEY_ARGUMENTS[industry],
    }
    path = CLAIMS_DIR / f"{RUNS[industry]}_01_core_claims.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _prompt_requirements(industry: str) -> list[dict[str, str]]:
    common = [
        ("界定研究产品、单位、转换、损耗和排除范围", "主文档", "不同资源、产品和财务口径不得混算"),
        ("梳理产业链、价格形成、成本和利润传导", "主文档", "说明上游资源到终端和回收的完整链条"),
        ("复盘2015—2025周期与供给预测失效原因", "Q0", "历史用于约束当前项目兑现而不是事后叙事"),
        ("计算全球与中国的国家、企业和产品CR3/CR5", "Q1", "统一同年分母，不能把矿端和化学品销售混算"),
        ("建立2025—2028供需基准与上下行情景", "Q2", "列出输入、公式、结果、外部对账和反方"),
        ("覆盖国内外主要公司和项目，不以本地公司池为上限", "Q1", "重点公司之外仍有完整全球竞争版图"),
        ("分析资源民族主义、出口、税费、许可、社区和能源", "Q5", "政策必须传导到有效供给、成本或现金"),
        ("分别拆解13家公司的资源、加工、其他业务和项目兑现", "Q3与公司透视", "不同商业模式分别建模"),
        ("先冻结FY1—FY3独立模型，再读取Wind与近期机构预测", "估值", "保存哈希，不反向修改独立输入"),
        ("执行PE、PB—ROE、FCFE、SOTP/NAV及反向估值门禁", "估值", "只使用经济逻辑和数据均适用的方法"),
        ("完整公司页覆盖财务、估值带、回报质量、预测与交易观察", "公司透视", "重点公司页面不得为空"),
        ("Q0—Q7章首设置可独立阅读的本章综述", "Q0—Q7", "先给核心结论、投资含义和证伪条件"),
        ("本地研报链与开放网络链分别检索和评级", "证据底稿", "英文与中文同类型资料同级"),
        ("缺资料时先二轮定向搜索并记录口径冲突", "全部栏目", "不能用无法判断代替继续搜索"),
        ("时序和多主体结果使用少量高信息表格与图", "公开页面", "表格和图必须回答已提出的问题"),
        ("给出季度和年度监控指标与阈值", "Q7", "只保留能证实或证伪结论的指标"),
    ]
    special = (
        [
            ("区分锂金属、LCE、精矿、碳酸锂和氢氧化锂", "主文档", "任何换算均显示系数和局限"),
            ("按国家与项目建立全球锂有效供给，而非资源量加总", "Q1", "投产、爬坡、品位和权益均进入模型"),
            ("拆分动力、储能、消费电池和非电池需求", "Q2", "储能为独立增长轴，避免重复计量"),
        ]
        if industry == "锂"
        else [
            ("独立建立中国碳酸锂产量、进出口、库存和需求平衡", "Q1/Q2", "可用供给等式可复算"),
            ("比较盐湖、锂辉石、锂云母和回收路线成本", "Q4", "成本口径和副产品不同需分开"),
            ("实现可增删项目、保存情景和价格敏感性的网页计算器", "网页工具", "默认值、手动值和来源不互相覆盖"),
            ("测算13家公司终局利润、相对2025/FY1倍数和当前隐含PE", "估值", "终局年份按项目周期定义"),
        ]
    )
    return [
        {"question": q, "output_hint": output, "acceptance_criteria": criteria}
        for q, output, criteria in common + special
    ]


def workflow_request(industry: str) -> dict[str, Any]:
    return {
        "run_key": RUNS[industry],
        "track": "b",
        "title": (
            "全球锂资源供需、竞争与公司盈利估值"
            if industry == "锂"
            else "碳酸锂产品供需、价格弹性与公司估值"
        ),
        "research_question": (
            "未来三至五年全球锂资源有效供需、重点项目、国家政策和竞争格局如何变化，13家A股公司的资源自给、项目兑现、利润和估值分别如何演变？"
            if industry == "锂"
            else "未来三至五年中国碳酸锂产量、进口、库存、需求和价格如何变化，不同资源路线和13家公司在不同锂价下的利润、ROE、现金流和估值弹性如何？"
        ),
        "decision_use": "用于行业配置、项目监控、公司估值对账和预期差识别；不构成投资建议。",
        "scope": {
            "industry": industry,
            "core_companies": [
                "赣锋锂业", "融捷股份", "盛新锂能", "盐湖股份", "大中矿业",
                "雅化集团", "天华新能", "天齐锂业", "永杉锂业", "中矿资源",
                "藏格矿业", "西藏城投", "永兴材料",
            ],
            "core_regions": [
                "中国", "澳大利亚", "智利", "阿根廷", "津巴布韦", "马里",
                "巴西", "加拿大", "美国", "玻利维亚",
            ],
        },
        "time_window": {
            "historical_industry": "2015—2025",
            "industry_forecast": "2026—2028，必要时延伸2035",
            "independent_forecast": "FY2026—FY2028",
            "valuation_as_of": "2026-07-24",
            "research_as_of": AS_OF_DATE,
            "company_report_reconciliation": "研究截止日前最近两个季度",
        },
        "must_include": [row["question"] for row in _prompt_requirements(industry)],
        "exclusions": [
            "不把资源量、规划产能或原矿处理量当成可销售LCE。",
            "不把外购矿加工销量当成资源利润。",
            "不把供应商财务快照复制到research.db。",
            "不把卖方目标价、一致预期或当前市值作为独立模型答案。",
            "不把周期顶部ROE和低PE无条件永续化。",
        ],
        "special_constraints": [
            "完整理解用户Guidance和碳酸锂估值工作簿，迁移公式结构但重新核对输入。",
            "A股Wind为主、Tushare补缺；本任务Wind累计上限由用户明确提高到8000个观测。",
            "英文与中文同类型资料同级，近期公司预测只使用最近两个季度。",
            "每章按问题、证据/数据、建模方法、研究与分析、总结组织。",
            "公司页和网页计算器读取financial.db冻结模型，不在研究正文复制供应商执行日志。",
        ],
        "required_artifacts": [
            "industry_main", "q0_history", "q1_competition", "q2_market_space",
            "q3_company_moat", "q4_industry_economics", "q5_resource_politics",
            "q6_synthesis", "q7_supplement", "company_profile", "valuation",
            "industry_chain", "financial_model_freezes", "external_reconciliation",
        ] + (["web_calculator"] if industry == "碳酸锂" else []),
        "prompt_requirements": _prompt_requirements(industry),
    }


def _layout(fig: go.Figure, title: str, y_title: str = "") -> None:
    fig.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        template="plotly_white",
        font={"family": "Microsoft YaHei, Arial", "size": 14, "color": "#223047"},
        margin={"l": 74, "r": 30, "t": 78, "b": 62},
        legend={"orientation": "h", "y": 1.08, "x": 0.02},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        yaxis_title=y_title,
    )
    fig.update_xaxes(showgrid=False, automargin=True)
    fig.update_yaxes(gridcolor="#e8edf4", automargin=True)


def _write_figure(fig: go.Figure, stem: str, height: int = 610) -> dict[str, str]:
    VIS_DIR.mkdir(parents=True, exist_ok=True)
    html = VIS_DIR / f"{stem}.html"
    png = VIS_DIR / f"{stem}.png"
    fig.update_layout(width=1280, height=height)
    fig.write_html(html, include_plotlyjs=True, full_html=True)
    from playwright.sync_api import sync_playwright

    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.is_file():
        raise FileNotFoundError(chrome)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=str(chrome), args=["--disable-gpu"]
        )
        page = browser.new_page(
            viewport={"width": 1320, "height": height + 50}, device_scale_factor=1.2
        )
        page.goto(html.resolve().as_uri(), wait_until="load")
        page.wait_for_selector(".js-plotly-plot", state="visible", timeout=30000)
        page.locator(".js-plotly-plot").first.screenshot(
            path=str(png), animations="disabled"
        )
        browser.close()
    return {
        "html": html.relative_to(ROOT).as_posix(),
        "png": png.relative_to(ROOT).as_posix(),
    }


def build_charts() -> dict[str, dict[str, str]]:
    lithium = json.loads(LITHIUM_SD_PATH.read_text(encoding="utf-8"))
    carbonate = json.loads(CARBONATE_SD_PATH.read_text(encoding="utf-8"))
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    figures: dict[str, dict[str, str]] = {}

    rows = lithium["base_rows"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[row["year"] for row in rows], y=[row["available_supply_mt_lce"] for row in rows],
        mode="lines+markers", name="可用供给", line={"color": "#2563eb", "width": 3},
    ))
    fig.add_trace(go.Scatter(
        x=[row["year"] for row in rows], y=[row["demand_mt_lce"] for row in rows],
        mode="lines+markers", name="需求", line={"color": "#b42318", "width": 3},
    ))
    _layout(fig, "全球锂供需：澳大利亚政府2026年6月基准", "百万吨LCE")
    figures["lithium_balance"] = _write_figure(fig, "lithium_global_balance")

    country = lithium["country_mine_2025"]["rows"]
    fig = go.Figure(go.Bar(
        x=list(country.keys()), y=list(country.values()), marker_color="#b42318",
        text=[f"{value:.1f}" for value in country.values()], textposition="outside",
    ))
    _layout(fig, "2025年主要国家锂矿产量（美国未披露）", "千吨锂金属")
    figures["lithium_regions"] = _write_figure(fig, "lithium_2025_mine_countries")

    crows = carbonate["rows"]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=[row["year"] for row in crows],
        y=[row["available_supply_mt"] for row in crows],
        name="可用供给", marker_color="#2563eb",
    ), secondary_y=False)
    fig.add_trace(go.Bar(
        x=[row["year"] for row in crows],
        y=[row["demand_mt"] for row in crows],
        name="需求", marker_color="#b42318",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=[row["year"] for row in crows],
        y=[row["balance_mt"] * 100 for row in crows],
        name="余额（万吨）", mode="lines+markers",
        line={"color": "#f59e0b", "width": 3},
    ), secondary_y=True)
    _layout(fig, "中国碳酸锂产品平衡：产量、进口、出口与需求", "百万吨")
    fig.update_yaxes(title_text="余额（万吨）", secondary_y=True)
    figures["carbonate_balance"] = _write_figure(fig, "carbonate_china_balance")

    names, profits, shares = [], [], []
    for company in model["companies"]:
        names.append(company["company"])
        base = company["scenarios"]["基准情景"][1]
        profits.append(base["net_income_rmb_bn"] * 10.0)
        shares.append(base["resource_share_pct"])
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(
        x=names, y=profits, name="2027基准归母利润",
        marker_color="#b42318", text=[f"{value:.1f}" for value in profits],
        textposition="outside",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=names, y=shares, name="资源自给比例", mode="lines+markers",
        line={"color": "#2563eb", "width": 2.5},
    ), secondary_y=True)
    _layout(fig, "13家公司2027年基准利润与资源自给率", "亿元人民币")
    fig.update_yaxes(title_text="资源自给比例（%）", secondary_y=True)
    figures["company_model"] = _write_figure(fig, "lithium_company_2027_model", 680)
    return figures


def prepare(db_path: Path) -> dict[str, Any]:
    industries = ensure_industries(db_path)
    claims = {name: write_claims(name) for name in RUNS}
    CACHE.mkdir(parents=True, exist_ok=True)
    requests = {}
    for name in RUNS:
        path = CACHE / f"{RUNS[name]}_workflow_request.json"
        path.write_text(
            json.dumps(workflow_request(name), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        requests[name] = path
    charts = build_charts()
    result = {
        "schema_version": "lithium_dual_research_prepare.v1",
        "industries": industries,
        "claims": {
            name: {"path": path.relative_to(ROOT).as_posix(), "sha256": _file_sha(path)}
            for name, path in claims.items()
        },
        "workflow_requests": {
            name: {"path": path.relative_to(ROOT).as_posix(), "sha256": _file_sha(path)}
            for name, path in requests.items()
        },
        "models": {
            "company": {"path": MODEL_PATH.relative_to(ROOT).as_posix(), "sha256": _file_sha(MODEL_PATH)},
            "lithium_supply": {"path": LITHIUM_SD_PATH.relative_to(ROOT).as_posix(), "sha256": _file_sha(LITHIUM_SD_PATH)},
            "carbonate_supply": {"path": CARBONATE_SD_PATH.relative_to(ROOT).as_posix(), "sha256": _file_sha(CARBONATE_SD_PATH)},
        },
        "charts": charts,
    }
    audit = CACHE / "research_prepare_audit.json"
    audit.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["audit_path"] = audit.relative_to(ROOT).as_posix()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    print(json.dumps(prepare(args.db.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
