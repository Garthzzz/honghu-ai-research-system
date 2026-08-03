#!/usr/bin/env python
from __future__ import annotations

"""准备铜行业 B 轨 claims、行业壳与决策型可视化。

本脚本不直接写 ``industry_data_point``；数据点只能由统一 ingest 入口写入。
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
    from .copper_research_data import KEY_ARGUMENTS, SOURCE_SPECS, build_data_points
except ImportError:
    from copper_research_data import KEY_ARGUMENTS, SOURCE_SPECS, build_data_points


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
CACHE_DIR = ROOT / "cache" / "copper_research"
CLAIMS_DIR = ROOT / "cache" / "claims"
VIS_DIR = ROOT / "tools" / "viewer" / "static" / "generated" / "copper"
RUN_TAG = "copper_b_20260726"
INDUSTRY_NAME = "铜"
PARENT_NAME = "有色金属"
AS_OF_DATE = "2026-07-26"
INDEPENDENT_MODEL_PATH = (
    CACHE_DIR / "models" / "copper_independent_models_v2.json"
)
RECONCILIATION_PATH = (
    CACHE_DIR / "models" / "copper_external_reconciliation_v2.json"
)
SUPPLY_MODEL_PATH = (
    CACHE_DIR / "models" / "copper_supply_demand_model_v1.json"
)
REFERENCE_WORKBOOK_PATH = ROOT / "碳酸锂标的估值测算20260606.xlsx"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_industry() -> tuple[None, int]:
    """Ensure copper is an independently browsable top-level industry.

    Returns:
        ``(None, industry_id)``. The first value remains only for backward
        compatibility with the audit payload; no empty parent card is created.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "select id from industry where name=?", (INDUSTRY_NAME,)
        ).fetchone()
        if row:
            industry_id = int(row[0])
            conn.execute(
                """
                update industry
                   set parent_id=NULL,level=1,tier=1,status='深度跟踪',
                       core_dynamic=?,last_updated=?
                 where id=?
                """,
                (
                    (
                        "2026—2027精炼端表观近均衡但矿端利用率下行；"
                        "2028年以后关键在大型项目恢复、资源国政策与电网/电气化需求谁先兑现。"
                    ),
                    AS_OF_DATE,
                    industry_id,
                ),
            )
        else:
            industry_id = int(
                conn.execute(
                    """
                    insert into industry(
                      name,parent_id,level,tier,status,core_dynamic,last_updated
                    ) values(?,?,?,?,?,?,?)
                    """,
                    (
                        INDUSTRY_NAME,
                        None,
                        1,
                        1,
                        "深度跟踪",
                        (
                            "2026—2027精炼端表观近均衡但矿端利用率下行；"
                            "2028年以后关键在大型项目恢复、资源国政策与电网/电气化需求谁先兑现。"
                        ),
                        AS_OF_DATE,
                    ),
                ).lastrowid
            )
        conn.commit()
        return None, industry_id
    finally:
        conn.close()


def _source_payload(spec: dict[str, Any]) -> dict[str, Any]:
    row = dict(spec)
    source_file = row.pop("source_file", None)
    row["value_layer"] = (
        "双层" if int(row.get("quality_tier", 3)) <= 2 else "信息流"
    )
    row["source_subtype"] = (
        "company_filing"
        if row.get("is_primary_source") and source_file
        else "official_web"
        if row.get("is_primary_source")
        else "research_report"
    )
    row["is_forward_looking"] = int(
        row.get("source_ref")
        in {
            "icsg_forecast_20260423",
            "iea_gcm_2026",
            "pacific_copper_20260705",
            "orient_copper_20260721",
            "ivanhoe_kamoa_20260331",
            "rio_oyu_20260630",
            "fcx_grasberg_restart",
            "bhp_escondida_20260317",
            "teck_qb_outlook",
            "antofagasta_cent_2026",
            "southern_tia_maria_20260624",
            "fqm_panama_20260407",
        }
    )
    row["fetch_timestamp"] = f"{AS_OF_DATE}T18:00:00+08:00"
    row["independence_basis"] = row.pop("independence_rationale")
    row["note"] = row["independence_basis"]
    if source_file:
        row["source_file"] = f"papers/铜/{source_file}"
    return row


def write_claims() -> Path:
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    path = CLAIMS_DIR / f"{RUN_TAG}_01_core_claims.json"
    data_points = build_data_points()
    source_by_ref = {spec["source_ref"]: spec for spec in SOURCE_SPECS}
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
    used_refs = {point["source_ref"] for point in data_points}
    evidence_groups = {
        source_by_ref[ref]["independence_key"] for ref in used_refs
    }
    payload = {
        "meta": {
            "industry": INDUSTRY_NAME,
            "run_tag": RUN_TAG,
            "research_question": (
                "未来三至五年全球铜供需、重点项目和资源国政策如何变化；"
                "紫金矿业、洛阳钼业和五矿资源的权益产量、成本、利润、现金流与估值如何演变？"
            ),
            "scope": {
                "product": "矿山铜、精矿、粗铜/阳极铜、精炼铜、再生铜及主要加工和终端需求",
                "exclusions": (
                    "不把铜半成品产值并入精炼铜吨位；不把全部电网扩容归因于AI；"
                    "供应商财务和市场快照不复制进research.db"
                ),
                "market_cutoff": AS_OF_DATE,
            },
            "evidence_accounting": {
                "observation_count": len(data_points),
                "parallel_research_fact_count": len(fact_identities),
                "used_source_independent_evidence_group_count": len(
                    evidence_groups
                ),
                "registered_source_independent_evidence_group_count": len(
                    {spec["independence_key"] for spec in SOURCE_SPECS}
                ),
                "note": (
                    "同一来源、主体、指标、单位和研究范围的跨期序列在研究事实层合并；"
                    "观测数不等于独立证据数。"
                ),
            },
        },
        "sources": [_source_payload(spec) for spec in SOURCE_SPECS],
        "data_points": data_points,
        "key_arguments": KEY_ARGUMENTS,
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
            "color": "#223047",
        },
        margin={"l": 80, "r": 34, "t": 84, "b": 68},
        legend={"orientation": "h", "y": 1.08, "x": 0.02},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        hoverlabel={"font_size": 14},
        yaxis_title=y_title,
    )
    fig.update_xaxes(showgrid=False, automargin=True)
    fig.update_yaxes(gridcolor="#e8edf4", automargin=True)


def _write_figure(fig: go.Figure, stem: str, height: int = 660) -> dict[str, str]:
    VIS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = VIS_DIR / f"{stem}.html"
    png_path = VIS_DIR / f"{stem}.png"
    fig.update_layout(width=1320, height=height)
    fig.write_html(html_path, include_plotlyjs=True, full_html=True)

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
    figures: dict[str, dict[str, str]] = {}

    years = [2025, 2026, 2027, 2028, 2029, 2030]
    balances = [0.455, 0.096, 0.377, 0.174, -0.026, -0.326]
    statuses = ["ICSG估计", "ICSG预测", "ICSG预测", "研究估算", "研究估算", "研究估算"]
    fig = go.Figure(
        go.Bar(
            x=years,
            y=balances,
            marker_color=["#2563eb" if value >= 0 else "#b42318" for value in balances],
            text=[f"{value * 100:.1f}" for value in balances],
            textposition="outside",
            customdata=statuses,
            hovertemplate="%{x}年 · %{customdata}<br>余额 %{text}万吨<extra></extra>",
            name="供应过剩为正、短缺为负",
        )
    )
    fig.add_hline(y=0, line_color="#475569", line_width=1.5)
    _layout(fig, "全球精炼铜年度供需余额：2028年后由研究模型延伸", "百万吨")
    figures["balance"] = _write_figure(fig, "copper_refined_balance")

    countries = ["智利", "刚果（金）", "秘鲁", "中国", "俄罗斯", "赞比亚", "澳大利亚", "印度尼西亚"]
    production = [5.3, 3.2, 2.7, 1.8, 1.3, 0.94, 0.73, 0.71]
    reserves = [180, 80, 85, 41, 80, 21, 100, 21]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=countries,
            y=production,
            name="2025矿山产量",
            marker_color="#b42318",
            text=[f"{v:.2f}" for v in production],
            textposition="outside",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=countries,
            y=reserves,
            name="储量",
            mode="lines+markers",
            line={"color": "#2563eb", "width": 3},
            marker={"size": 9},
        ),
        secondary_y=True,
    )
    _layout(fig, "主要铜资源国：当期产量集中度高，储量并不等于短期有效供给")
    fig.update_yaxes(title_text="矿山产量（百万吨）", secondary_y=False)
    fig.update_yaxes(title_text="储量（百万吨）", secondary_y=True, gridcolor="rgba(0,0,0,0)")
    figures["countries"] = _write_figure(fig, "copper_country_production_reserves")

    global_companies = [
        "BHP",
        "Freeport",
        "Codelco",
        "紫金矿业",
        "Southern Copper",
        "Rio Tinto",
        "Glencore",
        "洛阳钼业",
        "Anglo American",
        "Antofagasta",
        "五矿资源",
        "Teck",
        "First Quantum",
    ]
    global_company_production = [
        201.70,
        153.45,
        143.97,
        108.51,
        95.43,
        88.30,
        85.16,
        74.11,
        69.50,
        65.37,
        50.57,
        45.35,
        39.60,
    ]
    fig = go.Figure(
        go.Bar(
            x=global_company_production[::-1],
            y=global_companies[::-1],
            orientation="h",
            marker_color=[
                "#b42318" if name in {"紫金矿业", "洛阳钼业", "五矿资源"} else "#2563eb"
                for name in global_companies[::-1]
            ],
            text=[f"{value:.2f}" for value in global_company_production[::-1]],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}<br>2025年披露铜产量 %{x:.2f} 万吨<extra></extra>",
        )
    )
    _layout(
        fig,
        "全球主要矿企2025年铜产量：红色为本报告重点建模公司",
        "",
    )
    fig.update_xaxes(title="公司披露铜产量（万吨）", range=[0, 225])
    fig.update_layout(showlegend=False, margin={"l": 150, "r": 70, "t": 84, "b": 68})
    figures["global_companies"] = _write_figure(
        fig,
        "copper_global_company_production",
        height=760,
    )

    fig = make_subplots(
        rows=1,
        cols=3,
        shared_yaxes=True,
        subplot_titles=(
            "紫金矿业（公司矿产铜口径）",
            "洛阳钼业（公司矿产铜口径）",
            "五矿资源（三矿100%产量合计）",
        ),
    )
    company_series = {
        "紫金矿业": (1, [2025, 2026, 2028], [1085.126, 1200, 1550]),
        "洛阳钼业": (2, [2025, 2026, 2027], [741.149, 790, 890]),
        "五矿资源": (3, [2025, 2026, 2028], [505.745, 500, 575]),
    }
    colors = {"紫金矿业": "#b42318", "洛阳钼业": "#2563eb", "五矿资源": "#f59e0b"}
    for name, (col, x, y) in company_series.items():
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines+markers+text",
                text=[f"{v:.0f}" for v in y],
                textposition="top center",
                name=name,
                line={"width": 3, "color": colors[name]},
                marker={"size": 9},
            ),
            row=1,
            col=col,
        )
        fig.update_xaxes(
            tickmode="array",
            tickvals=x,
            ticktext=[str(year) for year in x],
            row=1,
            col=col,
        )
    _layout(
        fig,
        "三家公司铜产量基数与研究基准路径：各自口径分别建模",
        "千吨",
    )
    fig.update_layout(
        showlegend=False,
        annotations=[
            {
                **annotation.to_plotly_json(),
                "font": {"size": 13, "color": "#334155"},
            }
            for annotation in fig.layout.annotations
        ]
    )
    figures["companies"] = _write_figure(fig, "copper_company_production")

    projects = [
        "Kamoa-Kakula",
        "Oyu Tolgoi",
        "Grasberg恢复",
        "QB二期",
        "Centinela二选厂",
        "Tía María",
        "Cobre Panamá",
        "Escondida新选厂",
    ]
    start = [2026, 2026, 2026, 2026, 2027, 2027, 2026, 2031]
    end = [2028, 2028, 2027, 2028, 2029, 2029, 2026.5, 2032]
    fig = go.Figure()
    for project, left, right in zip(projects, start, end):
        fig.add_trace(
            go.Scatter(
                x=[left, right],
                y=[project, project],
                mode="lines+markers",
                line={"width": 12, "color": "#b42318" if project != "Cobre Panamá" else "#94a3b8"},
                marker={"size": 8},
                showlegend=False,
                hovertemplate=f"{project}<br>%{{x}}<extra></extra>",
            )
        )
    _layout(fig, "全球重点铜项目：投产年份不是达产年份", "")
    fig.update_xaxes(
        range=[2025.7, 2032.3],
        tickmode="linear",
        dtick=1,
        title="建设、恢复或爬坡窗口",
    )
    figures["projects"] = _write_figure(fig, "copper_project_timeline")
    return figures


def write_audit(
    parent_id: int | None,
    industry_id: int,
    claims_path: Path,
    charts: dict[str, dict[str, str]],
) -> Path:
    data_points = build_data_points()
    independent_model = json.loads(
        INDEPENDENT_MODEL_PATH.read_text(encoding="utf-8")
    )
    reconciliation = json.loads(
        RECONCILIATION_PATH.read_text(encoding="utf-8")
    )
    supply_model = json.loads(
        SUPPLY_MODEL_PATH.read_text(encoding="utf-8")
    )
    source_by_ref = {spec["source_ref"]: spec for spec in SOURCE_SPECS}
    used_refs = {point["source_ref"] for point in data_points}
    audit = {
        "run_tag": RUN_TAG,
        "parent_industry_id": parent_id,
        "industry_id": industry_id,
        "as_of_date": AS_OF_DATE,
        "claims_path": str(claims_path.relative_to(ROOT)).replace("\\", "/"),
        "claims_sha256": _sha256(claims_path),
        "source_count": len(SOURCE_SPECS),
        "used_source_count": len(used_refs),
        "report_source_count": sum(
            source_by_ref[ref]["source_channel"] == "report" for ref in used_refs
        ),
        "web_source_count": sum(
            source_by_ref[ref]["source_channel"] == "web" for ref in used_refs
        ),
        "observation_count": len(data_points),
        "parallel_research_fact_count": len(
            {
                (
                    point["source_ref"],
                    point.get("company"),
                    point["metric"],
                    point["unit"],
                    point.get("scope_key"),
                )
                for point in data_points
            }
        ),
        "model_hashes": {
            "independent_company_models": independent_model["output_sha256"],
            "external_reconciliation": reconciliation["content_sha256"],
            "industry_supply_demand": supply_model["content_sha256"],
            "reference_workbook": "sha256:" + _sha256(
                REFERENCE_WORKBOOK_PATH
            ),
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
    parent_id, industry_id = ensure_industry()
    claims_path = write_claims()
    charts = {} if args.skip_charts else build_charts()
    audit_path = write_audit(parent_id, industry_id, claims_path, charts)
    print(
        json.dumps(
            {
                "parent_industry_id": parent_id,
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
