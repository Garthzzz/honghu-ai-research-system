#!/usr/bin/env python
from __future__ import annotations

"""准备锂电池行业 B 轨 claims、行业壳与决策型可视化。

本脚本不直接写 ``industry_data_point``；研究事实只能由统一 ingest 入口写入。
"""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from .lithium_battery_research_data import (
        KEY_ARGUMENTS,
        SOURCE_SPECS,
        build_data_points,
    )
except ImportError:
    from lithium_battery_research_data import (
        KEY_ARGUMENTS,
        SOURCE_SPECS,
        build_data_points,
    )


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
CACHE_DIR = ROOT / "cache" / "lithium_battery_research"
CLAIMS_DIR = ROOT / "cache" / "claims"
VIS_DIR = ROOT / "tools" / "viewer" / "static" / "generated" / "lithium_battery"
RUN_TAG = "lithium_battery_b_20260728"
INDUSTRY_NAME = "锂电池"
AS_OF_DATE = "2026-07-28"
MODEL_PATH = CACHE_DIR / "models" / "battery_independent_models_v1.json"
RECONCILIATION_PATH = CACHE_DIR / "models" / "battery_external_reconciliation_v1.json"
POLICY_PATH = CACHE_DIR / "models" / "battery_policy_scenarios_v1.json"
SUPPLY_DEMAND_PATH = (
    CACHE_DIR / "models" / "battery_industry_supply_demand_v1.json"
)
CALCULATOR_PATH = (
    ROOT / "config" / "battery_calculator_models" / "battery_calculator_model_v1.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_industry() -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT id FROM industry WHERE name=?", (INDUSTRY_NAME,)
        ).fetchone()
        core_dynamic = (
            "2026年动力需求稳健、储能需求加速，竞争由单纯扩产转向有效产能、"
            "产品结构、海外合规和现金回报；中国税制与美欧本地化政策开始直接"
            "重塑利润分配。"
        )
        if row:
            industry_id = int(row[0])
            conn.execute(
                """
                UPDATE industry
                   SET parent_id=NULL,level=1,tier=1,status='深度跟踪',
                       core_dynamic=?,last_updated=?
                 WHERE id=?
                """,
                (core_dynamic, AS_OF_DATE, industry_id),
            )
        else:
            industry_id = int(
                conn.execute(
                    """
                    INSERT INTO industry(
                      name,parent_id,level,tier,status,core_dynamic,last_updated
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        INDUSTRY_NAME,
                        None,
                        1,
                        1,
                        "深度跟踪",
                        core_dynamic,
                        AS_OF_DATE,
                    ),
                ).lastrowid
            )
        conn.commit()
        return industry_id
    finally:
        conn.close()


def _source_payload(spec: dict[str, Any]) -> dict[str, Any]:
    row = dict(spec)
    row["value_layer"] = (
        "双层" if int(row.get("quality_tier", 3)) <= 2 else "信息流"
    )
    row["source_subtype"] = (
        "company_filing"
        if row.get("is_primary_source") and row.get("source_file")
        else "official_web"
        if row.get("is_primary_source")
        else "industry_research"
    )
    row["is_forward_looking"] = int(
        row.get("source_ref")
        in {
            "infolink_ess_2026q1",
            "cn_consumption_tax_2026",
            "cn_export_rebate_2026",
            "irs_45x_final",
            "irs_pfe_2026",
            "eu_battery_regulation",
            "eu_due_diligence_delay",
            "eu_battery_booster",
            "iea_ev_batteries_2026",
            "iea_ev_summary_2026",
            "iea_ev_manufacturing_2026",
            "iea_critical_minerals_2026",
            "cn_storage_capacity_price_2026",
            "cn_battery_recycling_2026",
            "cn_battery_export_control_2025",
            "cn_battery_tech_export_catalog_2025",
            "eu_battery_passport_2026",
            "eu_industrial_accelerator_2026",
            "india_acc_pli_2026",
            "brazil_storage_auction_2026",
        }
    )
    row["fetch_timestamp"] = f"{AS_OF_DATE}T18:00:00+08:00"
    row["independence_basis"] = row.pop("independence_rationale")
    row["note"] = row["independence_basis"]
    return row


def write_claims() -> Path:
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    path = CLAIMS_DIR / f"{RUN_TAG}_01_core_claims.json"
    data_points = build_data_points()
    source_by_ref = {item["source_ref"]: item for item in SOURCE_SPECS}
    used_refs = {point["source_ref"] for point in data_points}
    fact_identities = {
        (
            point["source_ref"],
            point.get("company"),
            point["metric"],
            point["unit"],
            point.get("scope_key"),
        )
        for point in data_points
    }
    key_arguments = [
        {
            "source_ref": source_ref,
            "argument": (
                f"{item['argument']}。该来源只构成联合证据链的一部分；"
                "与其余列明来源合并分析后的结论为："
                f"{item['conclusion']}"
            ),
            "dimension": "行业综合判断",
            "sentiment": "中性",
        }
        for item in KEY_ARGUMENTS
        for source_ref in item["evidence"]
    ]
    payload = {
        "meta": {
            "industry": INDUSTRY_NAME,
            "run_tag": RUN_TAG,
            "research_question": (
                "未来三至五年全球和中国动力、储能及其他锂电池需求、有效供给、"
                "技术、价格、盈利和竞争格局如何变化；中美欧政策怎样传导至九家"
                "重点公司的收入、利润、现金流、资本开支和估值？"
            ),
            "scope": {
                "product": (
                    "动力电池、储能电池、消费与其他电池；电芯、模组、PACK和"
                    "系统；上游材料与下游车辆/储能只研究到能够解释成本和需求。"
                ),
                "exclusions": (
                    "动力装机、储能出货和名义产能不混用；供应商财务、行情和"
                    "一致预期不复制进research.db；未获资格的补贴不进入基准利润。"
                ),
                "market_cutoff": AS_OF_DATE,
            },
            "evidence_accounting": {
                "observation_count": len(data_points),
                "parallel_research_fact_count": len(fact_identities),
                "used_source_independent_evidence_group_count": len(
                    {
                        source_by_ref[ref]["independence_key"]
                        for ref in used_refs
                    }
                ),
                "registered_source_independent_evidence_group_count": len(
                    {item["independence_key"] for item in SOURCE_SPECS}
                ),
                "note": (
                    "同一来源、主体、指标、单位和范围的序列在研究事实层合并；"
                    "转引同一协会底稿不作为多个独立证据。"
                ),
            },
        },
        "sources": [_source_payload(item) for item in SOURCE_SPECS],
        "data_points": data_points,
        "key_arguments": key_arguments,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _layout(fig: go.Figure, title: str, y_title: str = "") -> None:
    fig.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        template="plotly_white",
        font={
            "family": "Microsoft YaHei, Arial",
            "size": 15,
            "color": "#20314b",
        },
        margin={"l": 82, "r": 42, "t": 88, "b": 72},
        legend={"orientation": "h", "y": 1.08, "x": 0.02},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        hoverlabel={"font_size": 14},
        yaxis_title=y_title,
    )
    fig.update_xaxes(showgrid=False, automargin=True)
    fig.update_yaxes(gridcolor="#e7edf5", automargin=True)


def _write_figure(fig: go.Figure, stem: str, height: int = 660) -> dict[str, str]:
    VIS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = VIS_DIR / f"{stem}.html"
    png_path = VIS_DIR / f"{stem}.png"
    fig.update_layout(width=1320, height=height)
    fig.write_html(
        html_path,
        include_plotlyjs=True,
        full_html=True,
        config={"displaylogo": False, "responsive": True},
    )

    from playwright.sync_api import sync_playwright

    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        raise FileNotFoundError(f"Chrome executable not found: {chrome}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(chrome),
            args=["--disable-gpu"],
        )
        page = browser.new_page(
            viewport={"width": 1360, "height": height + 60},
            device_scale_factor=1.25,
        )
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        page.wait_for_selector(".js-plotly-plot", state="visible", timeout=30000)
        page.locator(".js-plotly-plot").first.screenshot(
            path=str(png_path), animations="disabled"
        )
        browser.close()
    return {
        "html": str(html_path.relative_to(ROOT)).replace("\\", "/"),
        "png": str(png_path.relative_to(ROOT)).replace("\\", "/"),
    }


def build_charts() -> dict[str, dict[str, str]]:
    charts: dict[str, dict[str, str]] = {}

    companies = [
        "宁德时代",
        "比亚迪",
        "LG新能源",
        "中创新航",
        "国轩高科",
        "亿纬锂能",
        "SK On",
        "松下",
        "蜂巢能源",
        "欣旺达",
    ]
    volumes = [188.4, 67.6, 41.0, 23.8, 21.7, 15.4, 15.8, 15.1, 12.1, 11.4]
    shares = [40.2, 14.4, 8.7, 5.1, 4.6, 3.3, 3.4, 3.2, 2.6, 2.4]
    colors = [
        "#b42318" if name in {"宁德时代", "比亚迪"} else
        "#2563eb" if name in COMPANY_NAMES else "#94a3b8"
        for name in companies
    ]
    fig = go.Figure(
        go.Bar(
            x=volumes[::-1],
            y=companies[::-1],
            orientation="h",
            marker_color=colors[::-1],
            text=[f"{s:.1f}%" for s in shares[::-1]],
            textposition="outside",
            cliponaxis=False,
            customdata=shares[::-1],
            hovertemplate="%{y}<br>装机 %{x:.1f}GWh<br>份额 %{customdata:.1f}%<extra></extra>",
        )
    )
    _layout(fig, "2026年1—5月全球动力电池装机：头部集中但第二梯队重排")
    fig.update_xaxes(title="装机量（GWh）", range=[0, 215])
    fig.update_layout(showlegend=False, margin={"l": 140, "r": 80, "t": 88, "b": 72})
    charts["global_power"] = _write_figure(
        fig, "battery_global_power_ranking_2026m5", height=720
    )

    fig = go.Figure()
    for metric, values, color in [
        ("CR3", [63.3, 69.37, None], "#b42318"),
        ("CR5", [73.0, 80.56, 58.9], "#2563eb"),
        ("CR10", [None, 93.9, 85.2], "#0f766e"),
    ]:
        fig.add_trace(
            go.Bar(
                name=metric,
                x=["全球动力装机<br>2026年1—5月", "中国动力装车<br>2026H1", "全球储能出货<br>2026Q1"],
                y=values,
                marker_color=color,
                text=["—" if value is None else f"{value:.1f}%" for value in values],
                textposition="outside",
                hovertemplate="%{x}<br>" + metric + " %{y:.2f}%<extra></extra>",
            )
        )
    _layout(fig, "三个不可混用的集中度分母：动力与储能、全球与中国", "%")
    fig.update_layout(barmode="group")
    fig.update_yaxes(range=[0, 105])
    charts["concentration"] = _write_figure(
        fig, "battery_market_concentration_comparison"
    )

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("中国电池生产、销售与使用", "销售去向与结构"),
    )
    fig.add_trace(
        go.Bar(
            x=["产量", "总销量", "动力装车"],
            y=[1068.9, 979.4, 335.6],
            marker_color=["#2563eb", "#0f766e", "#b42318"],
            text=["1,068.9", "979.4", "335.6"],
            textposition="outside",
            name="总量",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=["动力销量", "储能销量", "出口"],
            y=[661.3, 318.1, 181.3],
            marker_color=["#b42318", "#2563eb", "#f59e0b"],
            text=["661.3", "318.1", "181.3"],
            textposition="outside",
            name="结构",
        ),
        row=1,
        col=2,
    )
    _layout(fig, "2026年上半年中国动力与储能电池：产量不等于装车")
    fig.update_yaxes(title_text="GWh", row=1, col=1)
    fig.update_yaxes(title_text="GWh", row=1, col=2)
    fig.update_layout(showlegend=False)
    charts["china_flow"] = _write_figure(
        fig, "battery_china_production_sales_flow"
    )

    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    names, ni_2026, fcf_2026, roe_2026 = [], [], [], []
    for item in model["companies"]:
        forecast = next(row for row in item["forecast"] if row["year"] == 2026)
        names.append(item["company"])
        ni_2026.append(float(forecast["netIncome"]))
        fcf_2026.append(float(forecast["freeCashFlow"]))
        roe_2026.append(float(forecast["roe"]) * 100)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=names,
            y=ni_2026,
            name="2026E归母净利润",
            marker_color="#2563eb",
            text=[f"{value:.1f}" for value in ni_2026],
            textposition="outside",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=names,
            y=roe_2026,
            name="2026E ROE",
            mode="lines+markers",
            line={"color": "#b42318", "width": 3},
            marker={"size": 9},
        ),
        secondary_y=True,
    )
    _layout(fig, "九家公司2026年独立模型：利润规模与资本回报不是同一排名")
    fig.update_yaxes(title_text="归母净利润（亿元）", secondary_y=False)
    fig.update_yaxes(title_text="ROE（%）", secondary_y=True, gridcolor="rgba(0,0,0,0)")
    charts["company_models"] = _write_figure(
        fig, "battery_company_model_2026", height=700
    )

    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    exposure_names = []
    overseas = []
    risks = []
    risk_scale = {"中": 1, "中高": 2, "高": 3, "很高": 4}
    for item in policy["companyExposures"]:
        exposure_names.append(item["company"])
        overseas.append(float(item["reportedOverseasRevenuePct"]))
        risks.append(
            risk_scale.get(str(item["politicalRisk"]).split("：", 1)[0], 1)
        )
    fig = go.Figure(
        go.Bar(
            x=exposure_names,
            y=overseas,
            marker={
                "color": risks,
                "colorscale": [
                    [0.0, "#bfdbfe"],
                    [0.35, "#60a5fa"],
                    [0.7, "#f59e0b"],
                    [1.0, "#b42318"],
                ],
                "cmin": 1,
                "cmax": 4,
                "colorbar": {
                    "title": "政策风险<br>1低—4高",
                    "tickvals": [1, 2, 3, 4],
                },
            },
            text=[f"{value:.1f}%" for value in overseas],
            textposition="outside",
            customdata=risks,
            hovertemplate="%{x}<br>披露境外收入 %{y:.2f}%<br>政策风险档 %{customdata}<extra></extra>",
        )
    )
    _layout(fig, "九家公司披露的境外收入与政策风险：境外占比不是美国直供占比", "%")
    fig.update_yaxes(range=[0, 92])
    charts["policy_exposure"] = _write_figure(
        fig, "battery_company_policy_exposure", height=700
    )
    return charts


COMPANY_NAMES = {
    "宁德时代",
    "比亚迪",
    "国轩高科",
    "中创新航",
    "亿纬锂能",
    "瑞浦兰钧",
    "欣旺达",
    "鹏辉能源",
    "孚能科技",
}


def write_audit(
    industry_id: int,
    claims_path: Path,
    charts: dict[str, dict[str, str]],
) -> Path:
    points = build_data_points()
    source_by_ref = {item["source_ref"]: item for item in SOURCE_SPECS}
    used_refs = {point["source_ref"] for point in points}
    files = {
        "independent_company_models": MODEL_PATH,
        "external_reconciliation": RECONCILIATION_PATH,
        "policy_scenarios": POLICY_PATH,
        "industry_supply_demand": SUPPLY_DEMAND_PATH,
        "calculator_model": CALCULATOR_PATH,
    }
    audit = {
        "run_tag": RUN_TAG,
        "industry_id": industry_id,
        "as_of_date": AS_OF_DATE,
        "claims_path": str(claims_path.relative_to(ROOT)).replace("\\", "/"),
        "claims_sha256": "sha256:" + _sha256(claims_path),
        "source_count": len(SOURCE_SPECS),
        "used_source_count": len(used_refs),
        "report_source_count": sum(
            source_by_ref[ref]["source_channel"] == "report" for ref in used_refs
        ),
        "web_source_count": sum(
            source_by_ref[ref]["source_channel"] == "web" for ref in used_refs
        ),
        "observation_count": len(points),
        "parallel_research_fact_count": len(
            {
                (
                    point["source_ref"],
                    point.get("company"),
                    point["metric"],
                    point["unit"],
                    point.get("scope_key"),
                )
                for point in points
            }
        ),
        "model_hashes": {
            name: "sha256:" + _sha256(path)
            for name, path in files.items()
            if path.exists()
        },
        "charts": charts,
    }
    path = CACHE_DIR / "research_prepare_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-charts", action="store_true")
    args = parser.parse_args()
    industry_id = ensure_industry()
    claims_path = write_claims()
    charts = {} if args.skip_charts else build_charts()
    audit_path = write_audit(industry_id, claims_path, charts)
    print(
        json.dumps(
            {
                "industry_id": industry_id,
                "claims": str(claims_path),
                "audit": str(audit_path),
                "data_points": len(build_data_points()),
                "charts": charts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
