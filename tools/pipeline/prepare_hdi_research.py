#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Prepare the HDI B-track claims package and decision-useful charts.

This producer creates the industry shell, the claims JSON consumed by the
unified A/B ingest entry, and a small set of Plotly figures.  It deliberately
does not write ``industry_data_point``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import plotly.graph_objects as go

try:
    from .hdi_research_data import (
        AI_PCB_TAM_USD_MN,
        CHINA_HDI_SHARE_2024,
        GLOBAL_HDI_MARKET,
        GLOBAL_HDI_SHARE_2023,
        HDI_2024_APPLICATION,
        KEY_ARGUMENTS,
        SOURCE_SPECS,
        build_data_points,
    )
except ImportError:
    from hdi_research_data import (
        AI_PCB_TAM_USD_MN,
        CHINA_HDI_SHARE_2024,
        GLOBAL_HDI_MARKET,
        GLOBAL_HDI_SHARE_2023,
        HDI_2024_APPLICATION,
        KEY_ARGUMENTS,
        SOURCE_SPECS,
        build_data_points,
    )


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "research.db"
CACHE_DIR = ROOT / "cache" / "hdi_research"
CLAIMS_DIR = ROOT / "cache" / "claims"
VIS_DIR = ROOT / "tools" / "viewer" / "static" / "generated" / "hdi"
RUN_TAG = "hdi_b_20260726"
INDUSTRY_NAME = "HDI板"
AS_OF_DATE = "2026-07-26"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_industry() -> int:
    """Create the HDI child industry without touching research facts."""
    conn = sqlite3.connect(DB_PATH)
    try:
        parent = conn.execute("select id from industry where name='PCB制造'").fetchone()
        if not parent:
            raise RuntimeError("缺少父行业 PCB制造，不能创建 HDI板")
        row = conn.execute("select id from industry where name=?", (INDUSTRY_NAME,)).fetchone()
        if row:
            industry_id = int(row[0])
            conn.execute(
                """
                update industry
                   set parent_id=?,level=2,tier=1,status='深度跟踪',
                       core_dynamic=?,last_updated=?
                 where id=?
                """,
                (
                    int(parent[0]),
                    "AI服务器与高速交换把HDI从手机主板扩展到高层、高密度和高可靠互连；增量取决于架构、认证、良率和产能爬坡。",
                    AS_OF_DATE,
                    industry_id,
                ),
            )
        else:
            industry_id = int(
                conn.execute(
                    """
                    insert into industry(name,parent_id,level,tier,status,core_dynamic,last_updated)
                    values(?,?,?,?,?,?,?)
                    """,
                    (
                        INDUSTRY_NAME,
                        int(parent[0]),
                        2,
                        1,
                        "深度跟踪",
                        "AI服务器与高速交换把HDI从手机主板扩展到高层、高密度和高可靠互连；增量取决于架构、认证、良率和产能爬坡。",
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
    source_file = row.pop("source_file", None)
    row["value_layer"] = "双层" if int(row.get("quality_tier", 3)) <= 2 else "信息流"
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
            "victory_h_prospectus",
            "gs_ai_pcb_tam",
            "nomura_victory_20260713",
            "ubs_pengding_20260529",
            "gf_pengding_20260630",
            "cj_kinwong_20260628",
        }
    )
    row["fetch_timestamp"] = f"{AS_OF_DATE}T09:00:00+08:00"
    row["independence_basis"] = row.pop("independence_rationale")
    row["note"] = row["independence_basis"]
    if source_file:
        row["source_file"] = f"papers/HDI/{source_file}"
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
    effective_evidence_groups = {
        (
            source_by_ref[point["source_ref"]].get(
                "market_data_independence_key"
            )
            or source_by_ref[point["source_ref"]]["independence_key"]
        )
        for point in data_points
    }
    payload = {
        "meta": {
            "industry": INDUSTRY_NAME,
            "run_tag": RUN_TAG,
            "research_question": (
                "HDI刚性PCB的产品边界、技术演进、全球与中国市场空间、"
                "CR3/CR5竞争格局、AI服务器增量、制造壁垒和重点公司经营估值如何？"
            ),
            "scope": {
                "product": "刚性HDI及与AI服务器高层HDI/HLC相交的先进互连",
                "exclusions": "FPC、封装载板、普通低层PCB不并入HDI市场分母",
                "market_cutoff": AS_OF_DATE,
            },
            "evidence_accounting": {
                "observation_count": len(data_points),
                "parallel_research_fact_count": len(fact_identities),
                "bottom_source_independent_evidence_group_count": len(
                    effective_evidence_groups
                ),
                "registered_document_independence_group_count": len(
                    {spec["independence_key"] for spec in SOURCE_SPECS}
                ),
                "registered_bottom_source_independence_group_count": len(
                    {
                        spec.get("market_data_independence_key")
                        or spec["independence_key"]
                        for spec in SOURCE_SPECS
                    }
                ),
                "note": (
                    "平行事实数按来源、公司、指标、单位和研究范围合并，不代表独立证据数；"
                    "市场规模、地区和集中度优先使用market_data_independence_key合并同一"
                    "Prismark/CPCA底层表。"
                ),
            },
        },
        "sources": [_source_payload(spec) for spec in SOURCE_SPECS],
        "data_points": data_points,
        "key_arguments": KEY_ARGUMENTS,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _layout(fig: go.Figure, title: str, y_title: str) -> None:
    fig.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        template="plotly_white",
        font={"family": "Microsoft YaHei, Arial", "size": 15, "color": "#223047"},
        margin={"l": 72, "r": 28, "t": 78, "b": 62},
        legend={"orientation": "h", "y": 1.08, "x": 0.02},
        yaxis_title=y_title,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        hoverlabel={"font_size": 14},
    )
    fig.update_xaxes(showgrid=False, automargin=True)
    fig.update_yaxes(gridcolor="#e8edf4", automargin=True, rangemode="tozero")


def _write_figure(fig: go.Figure, stem: str) -> dict[str, str]:
    VIS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = VIS_DIR / f"{stem}.html"
    png_path = VIS_DIR / f"{stem}.png"
    fig.update_layout(width=1280, height=640)
    fig.write_html(html_path, include_plotlyjs=True, full_html=True)
    # Kaleido can hang on this Windows host.  Capture the same deterministic
    # Plotly DOM through the installed Chromium instead.
    from playwright.sync_api import sync_playwright

    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        raise FileNotFoundError(f"Chrome executable not found: {chrome}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=str(chrome), args=["--disable-gpu"]
        )
        page = browser.new_page(
            viewport={"width": 1320, "height": 700}, device_scale_factor=1.25
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

    years = list(GLOBAL_HDI_MARKET)
    values = [GLOBAL_HDI_MARKET[y][0] for y in years]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=values,
            mode="lines+markers+text",
            text=[f"{v:.2f}" for v in values],
            textposition="top center",
            line={"color": "#b42318", "width": 4},
            marker={"size": 11, "color": "#d92d20"},
            name="全球HDI市场",
        )
    )
    _layout(fig, "全球HDI市场：最新Prismark预测", "亿美元")
    fig.update_xaxes(
        tickmode="array", tickvals=years, ticktext=[str(year) for year in years]
    )
    fig.add_annotation(
        x=2027.8,
        y=205,
        text="2025—2030E CAGR 9.2%",
        showarrow=False,
        bgcolor="#fff1f0",
        bordercolor="#f04438",
    )
    figures["market"] = _write_figure(fig, "global_hdi_market")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=["CR3", "CR5", "扩展集中度"],
            y=[24.4, 37.2, 48.9],
            name="全球公司销售额（2023，扩展=CR7）",
            marker_color="#b42318",
            text=["24.4%", "37.2%", "48.9%"],
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            x=["CR3", "CR5", "扩展集中度"],
            y=[13.2, 17.5, 25.1],
            name="中国大陆生产地（2024，扩展=CR10）",
            marker_color="#f97066",
            text=["13.2%", "17.5%", "25.1%"],
            textposition="outside",
        )
    )
    _layout(fig, "HDI竞争格局：全球公司份额与大陆产值地口径不可混用", "份额（%）")
    fig.update_layout(barmode="group")
    figures["competition"] = _write_figure(fig, "hdi_competition")

    app = {k: v for k, v in HDI_2024_APPLICATION.items() if k != "其中：手机"}
    fig = go.Figure(
        go.Bar(
            x=list(app.values()),
            y=list(app.keys()),
            orientation="h",
            marker_color=["#b42318", "#d92d20", "#f04438", "#f97066", "#fda29b", "#fecdc9"],
            text=[f"{v:.2f}" for v in app.values()],
            textposition="outside",
        )
    )
    _layout(fig, "2024年全球HDI应用结构", "亿美元")
    fig.update_yaxes(categoryorder="total ascending")
    figures["application"] = _write_figure(fig, "hdi_application_2024")

    fig = go.Figure()
    for name, series in AI_PCB_TAM_USD_MN.items():
        if name not in {"AI服务器PCB合计", "GPU服务器PCB", "OAM", "交换机板"}:
            continue
        fig.add_trace(
            go.Scatter(
                x=list(series),
                y=[series[y] / 100 for y in series],
                mode="lines+markers",
                name=name,
                line={"width": 4 if name == "AI服务器PCB合计" else 2.5},
            )
        )
    _layout(fig, "AI服务器PCB情景：架构迁移是HDI需求的核心变量", "亿美元")
    ai_years = list(next(iter(AI_PCB_TAM_USD_MN.values())))
    fig.update_xaxes(
        tickmode="array",
        tickvals=ai_years,
        ticktext=[str(year) for year in ai_years],
    )
    figures["ai_tam"] = _write_figure(fig, "ai_server_pcb_tam")
    return figures


def write_audit(
    industry_id: int, claims_path: Path, charts: dict[str, dict[str, str]]
) -> Path:
    data_points = build_data_points()
    audit = {
        "run_tag": RUN_TAG,
        "industry_id": industry_id,
        "as_of_date": AS_OF_DATE,
        "claims_path": str(claims_path.relative_to(ROOT)).replace("\\", "/"),
        "claims_sha256": _sha256(claims_path),
        "source_count": len(SOURCE_SPECS),
        "report_source_count": sum(s["source_channel"] == "report" for s in SOURCE_SPECS),
        "web_source_count": sum(s["source_channel"] == "web" for s in SOURCE_SPECS),
        "parallel_data_point_count": len(data_points),
        "unique_metric_count": len({p["metric"] for p in data_points}),
        "cr_contract": {
            "global": "2023年全球HDI公司销售额份额，CR3/CR5/CR7",
            "china": "2024年中国大陆生产地HDI销售额份额，CR3/CR5/CR10",
            "warning": "两表年份、地域和分母不同；大陆产量占全球62.7%不是中国企业全球份额。",
        },
        "charts": charts,
    }
    path = CACHE_DIR / "research_prepare_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
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
