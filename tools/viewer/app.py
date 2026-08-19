#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
行研工具系统 Flask viewer
单文件 + Jinja 模板,端口 8080,只监听 127.0.0.1

路由:
    /                       — 首页 dashboard(Q5 综述 hero + 行业列表 + 数据总览)
    /industry/<id>          — 行业详情页(主文档 + Q0-Q5 七 Tab + 结构化数据)
    /q/<q>                  — Q0/Q1/Q2/Q3/Q4/Q5 跨行业横向页(/liang/<q> 为向后兼容别名)
    /chain/<id>             — 产业链全景页
    /source/<id>            — Source 详情页
    /companies              — 公司列表、搜索与最近研究入口
    /company/<id>           — 公司 tag 页(极简)
    /theme/<id>             — 主题详情页
    /pdf/<source_id>        — PDF 直接 serve(若 source 有 file_path)
    /data_points            — 数据点全览
    /sources                — Source 库
    /incremental            — 增量更新批次列表(任务 6)
    /refresh/<industry_id>  — 触发增量更新流程(任务 6)
    /api/health             — 烟测用
    /api/source/<id>        — Source JSON metadata(trace modal 用)
"""
import json
import gzip
import hashlib
import logging
import math
import os
import sys
import re
import sqlite3
import subprocess
import traceback
import uuid
from bisect import bisect_left, bisect_right
from datetime import datetime
from pathlib import Path
from statistics import median, quantiles
from typing import Any, Dict, List, Optional, Tuple

import frontmatter
import markdown as md_lib
from flask import (
    Flask, abort, g, has_request_context, jsonify, redirect, render_template, request,
    send_from_directory, url_for
)

# ── 路径 ──────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent.parent
# `python tools/viewer/app.py` 会把 tools/viewer 而不是项目根放进
# sys.path。先补项目根，再做统一绝对导入，使旧启动命令与 `python -m`
# 两种方式使用完全相同的模块，不依赖错误的 sibling fallback。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.financial.read_models import (  # noqa: E402
    company_bundle as financial_company_bundle,
    company_current_metrics_batch as financial_company_current_metrics_batch,
    company_page_summaries_batch as financial_company_page_summaries_batch,
    peer_asset_return_rows as financial_peer_asset_return_rows,
)
from tools.financial.valuation import historical_pb_roa, historical_pb_roe  # noqa: E402
from tools.financial.valuation_tracker import ValuationTrackerRepository  # noqa: E402
from tools.data_platform.postgres_runtime import (  # noqa: E402
    build_catalog_connection_factory,
    build_postgres_connection_factory,
    load_postgres_runtime_catalog,
    load_postgres_runtime_settings,
)
from tools.data_platform.domain_data import (  # noqa: E402
    DomainDataError,
    PostgresDomainReadCache,
    connect_domain_database,
)
from tools.data_platform.routing import (  # noqa: E402
    AuthorityMatrix,
    Backend as DataBackend,
    load_authority_matrix,
    load_cutover_route,
)
from tools.data_platform.shared_identity import (  # noqa: E402
    PostgresSharedIdentityResolver,
    PostgresSharedIdentityRepository,
    SharedIdentityConflict,
    SharedIdentityError,
    SharedIdentityReadCache,
    SharedIdentityWriterFenced,
)
from tools.data_platform.local_authority_fence import (  # noqa: E402
    LocalAuthorityFenceError,
    assert_sqlite_write_allowed,
)
from tools.data_platform.user_content_notes import (  # noqa: E402
    AnalystNoteError,
    AnalystNoteMutation,
    build_analyst_note_repository,
)
from tools.migration.stage4_identity_mapping import (  # noqa: E402
    IdentityMappingError,
    IdentityMappingResolver,
)
from tools.viewer.lithium_runtime import resolve_inputs as resolve_lithium_inputs  # noqa: E402
from tools.runtime_paths import (  # noqa: E402
    readonly_candidate_enabled,
    resolve_content_reference,
    resolve_runtime_layout,
)
from tools.viewer.user_content_security import (  # noqa: E402
    UserContentSecurityError,
    authenticate as authenticate_user_content,
    clear_principal as clear_user_content_principal,
    configure_user_content_security,
    current_principal as current_user_content_principal,
    ensure_csrf_token as ensure_user_content_csrf_token,
    load_security_settings,
    require_principal as require_user_content_principal,
    security_settings as current_user_content_security_settings,
)

RUNTIME_LAYOUT = resolve_runtime_layout(ROOT)
DB_PATH    = RUNTIME_LAYOUT.data_root / "research.db"
FINANCIAL_DB_PATH = RUNTIME_LAYOUT.data_root / "financial.db"
OPPORTUNITY_DB_PATH = RUNTIME_LAYOUT.data_root / "opportunity_lens.db"
DOCS_DIR   = RUNTIME_LAYOUT.content_root / "docs"
PAPERS_DIR = RUNTIME_LAYOUT.content_root / "papers"
CACHE_DIR  = RUNTIME_LAYOUT.cache_root
DEBUG_LOG  = CACHE_DIR / "viewer_debug.log"

CACHE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(DEBUG_LOG),
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("viewer")

# ── Plotly 图表(深度研究世界 · FUNDA 浅色风格)────────────
# 服务端生成图 → fig JSON 内嵌,前端懒加载(进入视口才 newPlot,见 base.html)。
# 用 plotly-cartesian 轻量子集(scatter/bar/heatmap),比全量小很多,首屏快。
# 纯表现层:不改任何 db/schema,仅把已有数据可视化。
PLOTLY_JS_CDN = "https://cdn.plot.ly/plotly-cartesian-3.4.0.min.js"
try:
    import plotly.graph_objects as go
    import plotly.io as pio
    _PLOTLY_OK = True
except Exception:  # plotly 缺失不应阻断页面
    _PLOTLY_OK = False

FUNDA_COLORWAY = ["#0d9488", "#2563eb", "#f59e0b", "#7c3aed",
                  "#dc2626", "#0891b2", "#16a34a", "#f97316"]


def _plotly_lazy(fig) -> str:
    """懒加载容器:页面先渲染,图进入视口才 newPlot(base.html 全局脚本)。"""
    if not _PLOTLY_OK or fig is None:
        return ""
    try:
        h = int(fig.layout.height or 300)
    except Exception:
        h = 300
    payload = pio.to_json(fig)
    return ('<div class="rx-plotly" data-plotly style="min-height:%dpx">'
            '<script type="application/json" class="fig">%s</script></div>' % (h, payload))


def _funda_layout(fig, height=None):
    fig.update_layout(
        template="plotly_white",
        font=dict(family="Noto Sans SC, system-ui, sans-serif", size=12, color="#475569"),
        margin=dict(l=6, r=18, t=8, b=26),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        colorway=FUNDA_COLORWAY, showlegend=False,
        hoverlabel=dict(bgcolor="#0f172a", font=dict(color="#ffffff", size=12), bordercolor="#0f172a"),
        bargap=0.34,
    )
    if height:
        fig.update_layout(height=height)
    fig.update_xaxes(gridcolor="rgba(15,23,42,0.06)", zeroline=False, tickfont=dict(size=11), automargin=True)
    fig.update_yaxes(gridcolor="rgba(15,23,42,0.06)", zeroline=False, tickfont=dict(size=11), automargin=True)
    return fig


def _fig_hbar(labels, values, texts, color="#0d9488", height=None, colors=None):
    """水平条形对比图(返回 fig)。labels/values 按降序传入,内部翻转使最大在顶。"""
    if not _PLOTLY_OK or not labels:
        return None
    labels = labels[::-1]; values = values[::-1]; texts = texts[::-1]
    marker = dict(color=(colors[::-1] if colors else color), line=dict(width=0))
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h", marker=marker,
        text=texts, textposition="outside", cliponaxis=False,
        textfont=dict(size=11, color="#334155"),
        hovertemplate="%{y} · %{text}<extra></extra>",
    ))
    _funda_layout(fig, height=height or max(140, 32 * len(labels) + 38))
    return fig


def _hbar_div(labels, values, texts, color="#0d9488", height=None, colors=None):
    return _plotly_lazy(_fig_hbar(labels, values, texts, color=color, height=height, colors=colors))


def _fig_network(nodes, edges, height=540):
    """分层网络图(semi 风格)。nodes: [{x,y,label,color,size,hover,url}];edges: [(i,j)]。
    节点 customdata=url → 前端 plotly_click 跳转。"""
    if not _PLOTLY_OK or not nodes:
        return None
    ex, ey = [], []
    for a, b in edges:
        ex += [nodes[a]["x"], nodes[b]["x"], None]
        ey += [nodes[a]["y"], nodes[b]["y"], None]
    edge_tr = go.Scatter(x=ex, y=ey, mode="lines", hoverinfo="skip",
                         line=dict(color="rgba(100,116,139,0.40)", width=1.4))
    node_tr = go.Scatter(
        x=[n["x"] for n in nodes], y=[n["y"] for n in nodes],
        mode="markers+text",
        text=[n["label"] for n in nodes], textposition="bottom center",
        textfont=dict(size=11.5, color="#0f172a"),
        marker=dict(size=[n.get("size", 30) for n in nodes],
                    color=[n.get("color", "#0d9488") for n in nodes],
                    line=dict(color="#ffffff", width=2.5), opacity=0.96,
                    symbol=[n.get("symbol", "circle") for n in nodes]),
        customdata=[n.get("url", "") for n in nodes],
        hovertext=[n.get("hover", n["label"]) for n in nodes], hoverinfo="text",
    )
    fig = go.Figure([edge_tr, node_tr])
    fig.update_layout(
        template="plotly_white", height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
        font=dict(family="Noto Sans SC, system-ui, sans-serif"),
        hoverlabel=dict(bgcolor="#0f172a", font=dict(color="#ffffff", size=12.5), align="left"),
        xaxis=dict(visible=False, fixedrange=False),
        yaxis=dict(visible=False, fixedrange=False),  # 标记是像素尺寸,无需锁纵横比,铺满更好看
        dragmode="pan",
    )
    return fig


def _network_div(nodes, edges, height=540, shapes=None, annotations=None):
    fig = _fig_network(nodes, edges, height=height)
    if fig is None:
        return ""
    if shapes:
        fig.update_layout(shapes=shapes)
    if annotations:
        fig.update_layout(annotations=annotations)
    return _plotly_lazy(fig)


app = Flask(
    __name__,
    template_folder=str(Path(__file__).resolve().parent / "templates"),
    static_folder=str(Path(__file__).resolve().parent / "static"),
)


@app.after_request
def _compress_large_public_pages(response):
    """Compress the read-only navigation pages that dominate LAN transfer."""

    public_endpoints = {
        "index", "research_home", "industry_detail", "companies_index",
        "sources_index", "data_points_index",
    }
    accepts_gzip = "gzip" in request.headers.get("Accept-Encoding", "").lower()
    if (
        request.method != "GET"
        or request.endpoint not in public_endpoints
        or response.status_code != 200
        or not accepts_gzip
        or response.headers.get("Content-Encoding")
        or response.is_streamed
    ):
        return response
    payload = response.get_data()
    if len(payload) < 1024:
        return response
    compressed = gzip.compress(payload, compresslevel=1)
    if len(compressed) >= len(payload):
        return response
    response.set_data(compressed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(compressed))
    response.headers.add("Vary", "Accept-Encoding")
    return response
app.config["HONGHU_READ_ONLY_CANDIDATE"] = readonly_candidate_enabled()
app.config["OPPORTUNITY_LENS_DB_PATH"] = OPPORTUNITY_DB_PATH

# The production runtime has one reviewed ownership registry and one durable
# PostgreSQL authority matrix.  Legacy per-unit files remain a compatibility
# entrypoint for the already deployed first two units, but new releases use
# this common control plane and never infer whole-system authority from one
# top-level backend label.
COMMON_POSTGRES_RUNTIME_PATH = os.environ.get("HONGHU_POSTGRES_RUNTIME_CONFIG")
COMMON_CUTOVER_REGISTRY_PATH = os.environ.get("HONGHU_CUTOVER_UNIT_REGISTRY")
if bool(COMMON_POSTGRES_RUNTIME_PATH) != bool(COMMON_CUTOVER_REGISTRY_PATH):
    raise RuntimeError(
        "production PostgreSQL runtime and cutover registry must be supplied together"
    )
POSTGRES_RUNTIME_CATALOG = None
AUTHORITY_MATRIX: AuthorityMatrix | None = None
COMMON_POSTGRES_READ_FACTORY = None
if COMMON_POSTGRES_RUNTIME_PATH:
    POSTGRES_RUNTIME_CATALOG = load_postgres_runtime_catalog(COMMON_POSTGRES_RUNTIME_PATH)
    COMMON_POSTGRES_READ_FACTORY = build_catalog_connection_factory(
        POSTGRES_RUNTIME_CATALOG, role="reader", pool_size=8
    )
    _, AUTHORITY_MATRIX = load_authority_matrix(
        COMMON_CUTOVER_REGISTRY_PATH, COMMON_POSTGRES_READ_FACTORY
    )

USER_CONTENT_TRACKED_ROUTE = ROOT / "config" / "migration" / "user_content_backend_route.json"
USER_CONTENT_RUNTIME_ROUTE = os.environ.get("HONGHU_USER_CONTENT_ROUTE_CONFIG")
USER_CONTENT_ROUTE = (
    AUTHORITY_MATRIX.route_for(
        "user_content_notes",
        writer_operation="analyst_note_mutation",
        transaction_boundary="one analyst-note mutation under the owning authority",
    )
    if AUTHORITY_MATRIX is not None
    else load_cutover_route(
        USER_CONTENT_TRACKED_ROUTE,
        runtime_override=USER_CONTENT_RUNTIME_ROUTE,
    )
)
USER_CONTENT_IDENTITY_RESOLVER = None
USER_CONTENT_POSTGRES_READ_FACTORY = None
USER_CONTENT_POSTGRES_WRITE_FACTORY = None
if USER_CONTENT_ROUTE.backend is DataBackend.POSTGRESQL_PRODUCTION:
    if AUTHORITY_MATRIX is not None:
        USER_CONTENT_POSTGRES_READ_FACTORY = COMMON_POSTGRES_READ_FACTORY
        USER_CONTENT_POSTGRES_WRITE_FACTORY = build_catalog_connection_factory(
            POSTGRES_RUNTIME_CATALOG, role="writer_user_content_notes"
        )
        USER_CONTENT_IDENTITY_RESOLVER = PostgresSharedIdentityResolver(
            COMMON_POSTGRES_READ_FACTORY
        )
    else:
        runtime_path = os.environ.get("HONGHU_USER_CONTENT_POSTGRES_CONFIG")
        if not runtime_path:
            raise RuntimeError("PostgreSQL user-content route requires runtime connection config")
        identity_mapping_path = os.environ.get("HONGHU_USER_CONTENT_IDENTITY_MAPPING")
        if not identity_mapping_path:
            raise RuntimeError("legacy PostgreSQL user-content route requires identity mapping")
        USER_CONTENT_IDENTITY_RESOLVER = IdentityMappingResolver.from_path(
            identity_mapping_path
        )
        postgres_settings = load_postgres_runtime_settings(runtime_path)
        USER_CONTENT_POSTGRES_READ_FACTORY = build_postgres_connection_factory(
            postgres_settings, role="reader"
        )
        USER_CONTENT_POSTGRES_WRITE_FACTORY = build_postgres_connection_factory(
            postgres_settings, role="writer"
        )

SHARED_IDENTITY_TRACKED_ROUTE = (
    ROOT / "config" / "migration" / "shared_identity_backend_route.json"
)
SHARED_IDENTITY_RUNTIME_ROUTE = os.environ.get("HONGHU_SHARED_IDENTITY_ROUTE_CONFIG")
SHARED_IDENTITY_ROUTE = (
    AUTHORITY_MATRIX.route_for(
        "shared_identity",
        writer_operation="shared_identity_mutation",
        transaction_boundary="one shared-identity mutation under the owning authority",
    )
    if AUTHORITY_MATRIX is not None
    else load_cutover_route(
        SHARED_IDENTITY_TRACKED_ROUTE,
        runtime_override=SHARED_IDENTITY_RUNTIME_ROUTE,
    )
)
SHARED_IDENTITY_READ_CACHE = None
SHARED_IDENTITY_POSTGRES_WRITE_FACTORY = None
SHARED_IDENTITY_REPOSITORY = None
if SHARED_IDENTITY_ROUTE.backend is DataBackend.POSTGRESQL_PRODUCTION:
    if AUTHORITY_MATRIX is not None:
        shared_reader_factory = COMMON_POSTGRES_READ_FACTORY
        SHARED_IDENTITY_POSTGRES_WRITE_FACTORY = build_catalog_connection_factory(
            POSTGRES_RUNTIME_CATALOG, role="writer_shared_identity"
        )
    else:
        shared_runtime_path = os.environ.get("HONGHU_SHARED_IDENTITY_POSTGRES_CONFIG")
        if not shared_runtime_path:
            raise RuntimeError("PostgreSQL shared-identity route requires runtime config")
        shared_settings = load_postgres_runtime_settings(shared_runtime_path)
        shared_reader_factory = build_postgres_connection_factory(
            shared_settings, role="reader"
        )
        SHARED_IDENTITY_POSTGRES_WRITE_FACTORY = build_postgres_connection_factory(
            shared_settings, role="writer"
        )
    SHARED_IDENTITY_READ_CACHE = SharedIdentityReadCache(shared_reader_factory)
    SHARED_IDENTITY_REPOSITORY = PostgresSharedIdentityRepository(
        shared_reader_factory,
        SHARED_IDENTITY_POSTGRES_WRITE_FACTORY,
        SHARED_IDENTITY_ROUTE,
    )

VALUATION_TRACKER_REPOSITORY = None
VALUATION_TRACKER_POSTGRES_WRITE_FACTORY = None
if AUTHORITY_MATRIX is not None:
    valuation_route = AUTHORITY_MATRIX.routes.get("financial_data")
    if valuation_route is not None and valuation_route.backend is DataBackend.POSTGRESQL_PRODUCTION:
        VALUATION_TRACKER_POSTGRES_WRITE_FACTORY = build_catalog_connection_factory(
            POSTGRES_RUNTIME_CATALOG, role="writer_financial_data"
        )
        VALUATION_TRACKER_REPOSITORY = ValuationTrackerRepository(
            COMMON_POSTGRES_READ_FACTORY, VALUATION_TRACKER_POSTGRES_WRITE_FACTORY
        )

DOMAIN_READ_CACHES: dict[str, PostgresDomainReadCache] = {}
if AUTHORITY_MATRIX is not None:
    for unit in (
        "research_publication",
        "dynamic_intelligence",
        "operations_governance",
        "investment_hypotheses",
    ):
        if AUTHORITY_MATRIX.routes[unit].backend is DataBackend.POSTGRESQL_PRODUCTION:
            DOMAIN_READ_CACHES[unit] = PostgresDomainReadCache(
                unit, COMMON_POSTGRES_READ_FACTORY
            )

configure_user_content_security(
    app,
    load_security_settings(os.environ.get("HONGHU_USER_CONTENT_SECURITY_CONFIG")),
)

try:
    from .opportunity_lens_blueprint import opportunity_lens_bp
except ImportError:
    from opportunity_lens_blueprint import opportunity_lens_bp
app.register_blueprint(opportunity_lens_bp)


@app.before_request
def enforce_readonly_candidate_mode():
    """Make a Phase 2 parallel candidate incapable of HTTP mutations."""
    if app.config.get("HONGHU_READ_ONLY_CANDIDATE") and request.method not in {
        "GET",
        "HEAD",
        "OPTIONS",
    }:
        return jsonify(
            {
                "ok": False,
                "error": "read-only candidate blocks mutation methods",
                "viewer_mode": "readonly_candidate",
            }
        ), 403


@app.route("/favicon.ico")
def favicon():
    """Browsers request this implicitly; return no content instead of a noisy 404."""
    return "", 204


# ── 研究维度配置(Q0-Q5,无人名)──────────────────────
# Q0-Q5 六维度，Q5 综述是面向决策者的核心摘要。
Q_DIMENSIONS = [
    ("Q0", "历史发展", "历史发展与代际规律"),
    ("Q1", "竞争格局", "竞争格局"),
    ("Q2", "市场空间", "市场空间"),
    ("Q3", "公司壁垒", "公司壁垒"),
    ("Q4", "行业特征", "行业特征与商业模式"),
    ("Q5", "综述",     "综述"),
]
Q_SUFFIX_MAP = {q: f"_{q}_{short}.md" for q, short, _ in Q_DIMENSIONS}
Q_TITLE_MAP  = {q: full for q, _, full in Q_DIMENSIONS}
Q_SHORT_MAP  = {q: short for q, short, _ in Q_DIMENSIONS}


def industry_q_dimensions(industry_name: str) -> List[Tuple[str, str, str]]:
    """Return an industry's declared research dimensions, with legacy fallback.

    Most industries keep the stable Q0-Q5 contract.  A small number of mature
    research packages need one or two domain-specific axes; those packages may
    declare them in ``docs/industries/<name>_dimensions.json`` without changing
    every other industry or the cross-industry Q pages.
    """
    path = DOCS_DIR / "industries" / f"{industry_name}_dimensions.json"
    if not path.is_file():
        return list(Q_DIMENSIONS)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        log.warning("invalid industry dimension manifest: %s", path)
        return list(Q_DIMENSIONS)
    result: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for raw in payload if isinstance(payload, list) else []:
        if not isinstance(raw, dict):
            continue
        q = str(raw.get("q") or "").strip().upper()
        short = str(raw.get("short") or "").strip()
        full = str(raw.get("full") or short).strip()
        if not re.fullmatch(r"Q\d{1,2}", q) or not short or not full or q in seen:
            continue
        seen.add(q)
        result.append((q, short, full))
    return result or list(Q_DIMENSIONS)


# ── 中英映射(任务 5d:LABEL_MAP + t() 函数)───────────
# 用途:db 字段保留英文 ID(向后兼容稳定),viewer 渲染翻译为中文显示。
# Jinja 模板里所有英文枚举字段用 {{ t(field) }} 包一层。
LABEL_MAP: Dict[str, str] = {
    # industry_relation.bargaining_power
    "upstream_strong":   "上游议价强势",
    "balanced":          "相对均衡",
    "downstream_strong": "下游议价强势",
    # source.source_type
    "claude_lit_review": "AI 自主综合",
    "website_material":  "网站材料",
    # thesis.direction
    "bullish": "看多",
    "bearish": "看空",
    "neutral": "中性",
    "paired":  "配对",
    # thesis.confidence
    "high":   "高",
    "medium": "中",
    "low":    "低",
    # thesis.status / general
    "active":    "跟踪中",
    "verified":  "已验证",
    "falsified": "已证伪",
    "paused":    "暂停",
    # thesis_kpi.expected_direction
    "up":    "上行",
    "down":  "下行",
    "range": "区间",
    # evidence_strength(语义同 confidence,但语境不同)
    "strong": "高",
    "weak":   "低",
    # 历史遗留英文标签(litreview Step 4 旧产物)
    "ROBUST":      "一致",
    "INCREMENTAL": "增量",
    "CONFLICT":    "冲突",
    "NEW":         "新发现",
    # 多源对照 consensus_status(第三次修订任务 2)
    "unevaluated": "未评估",
    # 共识 / 主流 / 次主流 / 离群 / 孤证 已是中文,t() 透传
    # ── Phase3 公司透视:listing_status ──
    "a_share":      "A股",
    "listed":       "已上市",
    "hk":           "港股",
    "us":           "美股",
    "kospi":        "韩股",
    "tse":          "日股",
    "other_listed": "其他交易所",
    "unlisted":     "未上市",
    "private":      "未上市",
    "private_subsidiary": "未上市子公司",
    "parent_subsidiary":  "未上市子公司",
    "soe":          "未上市国企",
    "pre_ipo":      "拟上市",
    "delisted":     "已退市",
    # ── Phase3 source_credibility ──
    "whitelisted":  "白名单",
    "blacklisted":  "黑名单",
    # 'unverified' 已映射为 '未评估'(语义在 credibility 语境=未验证/灰名单),透传即可
    # ── Phase3 display_mode ──
    "quantitative":     "定量",
    "qualitative_only": "仅定性",
    # ── Phase3 fetch_method ──
    "pdf_local":    "本地PDF",
    "api_yfinance": "yfinance",
    "api_tushare":  "Tushare",
}

UNLISTED_LISTING_STATUSES = {
    "delisted",
    "unlisted",
    "private",
    "private_subsidiary",
    "parent_subsidiary",
    "soe",
    "pre_ipo",
}


def t(label: Any) -> str:
    """Translate label: db 英文枚举 → 中文显示。
    None / 空串 → ""; 未在 LABEL_MAP 命中 → 原样返回(已是中文则透传)。
    """
    if label is None:
        return ""
    s = str(label).strip()
    if not s:
        return ""
    return LABEL_MAP.get(s, s)


app.jinja_env.globals["t"] = t
app.jinja_env.globals["Q_DIMENSIONS"] = Q_DIMENSIONS
app.jinja_env.globals["Q_SHORT_MAP"]  = Q_SHORT_MAP
app.jinja_env.globals["Q_TITLE_MAP"]  = Q_TITLE_MAP

# ── 风险维度标签(2c-G 任务 2:分类标签中性化,事实性表述保留在正文)──
# "技术路线被颠覆" → "技术路线"(标签不带感情色彩);其余本就中性。
RISK_DIM_LABEL = {
    "cyclical":                    "周期性",
    "customer_concentration_risk": "客户集中度",
    "supply_chain_risk":           "供应链",
    "geopolitical_risk":           "地缘政治",
    "tech_route_risk":             "技术路线",
    "regulatory_risk":             "监管合规",
}


def risk_label(rk: Any) -> str:
    """风险条目显示标签:优先按 dim 中性映射,回退 dim_label。"""
    if isinstance(rk, dict):
        d = rk.get("dim")
        if d and d in RISK_DIM_LABEL:
            return RISK_DIM_LABEL[d]
        return rk.get("dim_label") or ""
    return ""


app.jinja_env.globals["risk_label"] = risk_label

# ── Stage 3-G:industry tag 5 色分组(config 驱动;tag 只到产业链一环)──────────
import yaml as _yaml  # noqa: E402
try:
    _dyn_cfg = _yaml.safe_load((ROOT / "tools" / "dynamic" / "config.yaml").read_text(encoding="utf-8"))
    _IND_COLOR_GROUPS = _dyn_cfg.get("industry_color_groups", {}) or {}
    _RESEARCH_SECTORS = _dyn_cfg.get("research_sectors", {}) or {}
    _AI_CHAIN_DIRECTIONS = _dyn_cfg.get("ai_chain_directions", []) or []
except Exception:
    _IND_COLOR_GROUPS = {}
    _RESEARCH_SECTORS = {}
    _AI_CHAIN_DIRECTIONS = []
_IND_NAME_TO_GROUP = {nm: g for g, names in _IND_COLOR_GROUPS.items() for nm in names}
_IND_NAME_TO_SECTOR = {
    name: sector_name
    for sector_name, sector in _RESEARCH_SECTORS.items()
    for name in (sector.get("industries") or [])
}


def _derive_industry_group_assignments(
    industry_rows: List[Dict[str, Any]],
    group_configs: Dict[str, Dict[str, Any]],
    *,
    relations: List[Dict[str, Any]] | None = None,
    eligible_names: set[str] | None = None,
    minimum_relation_votes: int = 2,
) -> Dict[str, str]:
    """Derive stable Viewer groups from anchors, parents, and relation votes.

    Configuration keeps only stable top-level anchors. Child industries first
    inherit their parent's group; relation voting is an optional second pass
    for views such as value-chain lanes. Ties and weak single-edge evidence
    stay unassigned instead of manufacturing a category.
    """
    rows = [dict(row) for row in industry_rows]
    by_id = {int(row["id"]): row for row in rows}
    by_name = {str(row["name"]): row for row in rows}
    assignments: Dict[str, str] = {}
    for group_name, config in group_configs.items():
        for name in config.get("industries") or []:
            if name in by_name:
                assignments.setdefault(str(name), str(group_name))

    changed = True
    while changed:
        changed = False
        for row in rows:
            name = str(row["name"])
            if name in assignments:
                continue
            parent_id = row.get("parent_id")
            parent = by_id.get(int(parent_id)) if parent_id is not None else None
            parent_group = assignments.get(str(parent["name"])) if parent else None
            if parent_group:
                assignments[name] = parent_group
                changed = True

    relation_rows = [dict(row) for row in (relations or [])]
    if relation_rows:
        allowed = set(by_name if eligible_names is None else eligible_names)
        changed = True
        while changed:
            changed = False
            for row in rows:
                name = str(row["name"])
                if name in assignments or name not in allowed:
                    continue
                vote_neighbors: Dict[str, set[int]] = {}
                industry_id = int(row["id"])
                for relation in relation_rows:
                    neighbor_id = None
                    if int(relation["upstream_id"]) == industry_id:
                        neighbor_id = int(relation["downstream_id"])
                    elif int(relation["downstream_id"]) == industry_id:
                        neighbor_id = int(relation["upstream_id"])
                    if neighbor_id is None or neighbor_id not in by_id:
                        continue
                    neighbor_group = assignments.get(str(by_id[neighbor_id]["name"]))
                    if neighbor_group:
                        vote_neighbors.setdefault(neighbor_group, set()).add(neighbor_id)
                votes = {
                    group_name: len(neighbor_ids)
                    for group_name, neighbor_ids in vote_neighbors.items()
                }
                ranked = sorted(votes.items(), key=lambda item: (-item[1], item[0]))
                if not ranked or ranked[0][1] < minimum_relation_votes:
                    continue
                if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
                    continue
                assignments[name] = ranked[0][0]
                changed = True
    return assignments


def industry_color_class(name: Any) -> str:
    """板块名 → 5 色组 class(v2:software紫/silicon橙/optical蓝/network青/infra绿)。"""
    return "tag-" + _IND_NAME_TO_GROUP.get(str(name or ""), "default")


app.jinja_env.globals["industry_color_class"] = industry_color_class


# ── Phase3 数据时效性四色(CLAUDE_COMPANY_PROFILE.md Section C2)─────
# 估值类字段窗口更严(绿<7天);常规字段绿<30天。
# 存量 dp 的 last_verified_at 留 NULL,基准回退 created_at(协议 C1)。
from datetime import date as _date  # noqa: E402


def _days_since(iso_str: Any) -> Optional[int]:
    if not iso_str:
        return None
    s = str(iso_str)[:10]
    try:
        d = _date.fromisoformat(s)
    except Exception:
        return None
    try:
        return (_date.today() - d).days
    except Exception:
        return None


def freshness(last_verified_at: Any = None, created_at: Any = None,
              is_valuation: bool = False) -> Dict[str, str]:
    """返回 {color, label, days}。color ∈ green/yellow/orange/red/gray。
    基准 = last_verified_at or created_at(协议 C1)。"""
    basis = last_verified_at or created_at
    days = _days_since(basis)
    if days is None:
        return {"color": "gray", "label": "未知", "days": ""}
    if is_valuation:
        thresholds = [(7, "green", "最新"), (30, "yellow", "较新"),
                      (90, "orange", "偏旧"), (10**9, "red", "过期")]
    else:
        thresholds = [(30, "green", "最新"), (182, "yellow", "较新"),
                      (365, "orange", "偏旧"), (10**9, "red", "过期")]
    for lim, color, label in thresholds:
        if days < lim:
            return {"color": color, "label": label, "days": str(days)}
    return {"color": "red", "label": "过期", "days": str(days)}


def _json_or(default, raw):
    if not raw:
        return default
    try:
        v = json.loads(raw)
        return v if v is not None else default
    except Exception:
        return default


def _table_exists(name):
    try:
        return bool(query_one("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))
    except Exception:
        return False


app.jinja_env.globals["freshness"] = freshness


# ── DB 工具 ───────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    research_units = (
        "research_publication",
        "dynamic_intelligence",
        "operations_governance",
        "investment_hypotheses",
    )
    research_is_fully_postgresql = bool(
        AUTHORITY_MATRIX is not None
        and all(
            AUTHORITY_MATRIX.routes[unit].backend is DataBackend.POSTGRESQL_PRODUCTION
            for unit in research_units
        )
    )
    read_only_base = bool(
        app.config.get("HONGHU_READ_ONLY_CANDIDATE")
        or research_is_fully_postgresql
    )
    if read_only_base:
        conn = sqlite3.connect(
            f"file:{DB_PATH.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=10,
        )
    else:
        conn = sqlite3.connect(
            f"file:{DB_PATH.resolve().as_posix()}?mode=rwc",
            uri=True,
        )
    conn.row_factory = sqlite3.Row
    if SHARED_IDENTITY_READ_CACHE is not None:
        # TEMP views shadow only the legacy identity tables.  Remaining tables
        # still use their current SQLite authority during the mixed window.
        # Any missed identity write fails because SQLite views are read-only.
        SHARED_IDENTITY_READ_CACHE.attach(conn)
    for unit in research_units:
        cache = DOMAIN_READ_CACHES.get(unit)
        if cache is not None:
            cache.attach(conn)
    if read_only_base:
        conn.execute("PRAGMA query_only=ON")
    if not read_only_base:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_domain_write_db(unit: str, operation_scope: str):
    """Return the one authoritative writer for a reviewed Viewer mutation.

    SQLite-mode behavior stays backward compatible.  Once a unit is S3/S4,
    the request must carry the existing authenticated principal, CSRF token
    and a stable idempotency identity.  Failure never reopens SQLite.
    """

    route = AUTHORITY_MATRIX.routes[unit] if AUTHORITY_MATRIX is not None else None
    if route is None or route.backend is DataBackend.SQLITE_TRANSITION:
        return get_db()
    principal = require_user_content_principal(
        app, request, permission="analyst_note:write", csrf=True
    )
    operation_id = str(request.headers.get("X-Idempotency-Key") or "").strip()
    if not operation_id:
        raise UserContentSecurityError(
            "X-Idempotency-Key is required for a PostgreSQL domain mutation",
            code="idempotency_required",
            http_status=400,
        )
    return connect_domain_database(
        unit,
        DB_PATH,
        readonly=False,
        operation_scope=operation_scope,
        operation_id=operation_id,
        actor=principal.subject,
    )


@app.errorhandler(DomainDataError)
def _domain_data_error(exc: DomainDataError):
    return jsonify(
        {"ok": False, "error": str(exc), "code": "domain_writer_fenced"}
    ), 503


@app.errorhandler(UserContentSecurityError)
def _user_content_security_error(exc: UserContentSecurityError):
    return jsonify({"ok": False, "error": str(exc), "code": exc.code}), exc.http_status


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


_REQUEST_READ_DB_KEY = "_honghu_viewer_read_db"
_REQUEST_SENTI_DB_KEY = "_honghu_viewer_sentiment_read_db"


def _request_read_connection() -> tuple[sqlite3.Connection, bool]:
    """Reuse the expensive PostgreSQL compatibility projection per request."""

    if not has_request_context():
        return get_db(), True
    connection = getattr(g, _REQUEST_READ_DB_KEY, None)
    if connection is None:
        connection = get_db()
        setattr(g, _REQUEST_READ_DB_KEY, connection)
    return connection, False


@app.teardown_request
def _close_request_read_connection(_error: BaseException | None) -> None:
    for key in (_REQUEST_READ_DB_KEY, _REQUEST_SENTI_DB_KEY):
        connection = getattr(g, key, None)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                log.exception("关闭 Viewer 请求级只读连接失败 key=%s", key)
            finally:
                delattr(g, key)


def query_all(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn, owned = _request_read_connection()
    try:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        if owned:
            conn.close()


def query_one(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    conn, owned = _request_read_connection()
    try:
        cur = conn.execute(sql, params)
        return row_to_dict(cur.fetchone())
    finally:
        if owned:
            conn.close()


_INDUSTRY_OVERVIEW_SELECT = """
    SELECT
        i.id, i.name, i.parent_id, i.tier, i.status,
        i.core_dynamic, i.last_updated,
        (SELECT COUNT(*) FROM source_entity se
         WHERE se.entity_type='industry' AND se.entity_id=CAST(i.id AS TEXT))
            AS source_count,
        (SELECT COUNT(*) FROM industry_data_point dp
         WHERE dp.industry_id=i.id) AS data_point_count,
        (SELECT COUNT(DISTINCT ci.company_id) FROM company_industry ci
         WHERE ci.industry_id=i.id) AS company_count,
        (SELECT COUNT(*) FROM thesis t
         WHERE t.industry_id=i.id AND t.status='active') AS active_thesis_count
    FROM industry i
"""


def _industry_overview_rows(
    *, deep_only: bool = False, navigation_order: bool = False,
) -> List[Dict[str, Any]]:
    """Build industry summaries from the current authoritative projections.

    The legacy ``v_industry_overview`` is a persistent SQLite view. SQLite
    resolves tables referenced by a persistent view in its own ``main``
    schema, so that view cannot see the TEMP tables attached from PostgreSQL
    after a domain cutover. Querying the projected tables directly keeps new
    PostgreSQL industries visible on /research, navigation and Q pages.
    """

    sql = _INDUSTRY_OVERVIEW_SELECT
    if deep_only:
        sql += " WHERE i.status='深度跟踪'"
    if navigation_order:
        sql += " ORDER BY (i.status='深度跟踪') DESC, i.tier ASC, i.name ASC"
    else:
        sql += " ORDER BY i.tier ASC, i.name ASC"
    rows = query_all(sql)
    for row in rows:
        if row.get("id") is None or not str(row.get("name") or "").strip():
            raise RuntimeError("industry overview projection returned an invalid row")
    return rows


def analyst_note_repository():
    return build_analyst_note_repository(
        USER_CONTENT_ROUTE,
        sqlite_connection_factory=get_db,
        postgres_read_connection_factory=USER_CONTENT_POSTGRES_READ_FACTORY,
        postgres_write_connection_factory=USER_CONTENT_POSTGRES_WRITE_FACTORY,
    )


def analyst_note_entity_key(entity_type: str, entity_id: str | int) -> str:
    if USER_CONTENT_ROUTE.backend is DataBackend.SQLITE_TRANSITION:
        return f"sqlite-transition:{entity_type}:{entity_id}"
    if USER_CONTENT_IDENTITY_RESOLVER is None:
        raise IdentityMappingError("authoritative shared identity resolver is unavailable")
    return USER_CONTENT_IDENTITY_RESOLVER.resolve(entity_type, entity_id)


def _user_content_error(exc: Exception):
    if isinstance(exc, (UserContentSecurityError, AnalystNoteError)):
        return jsonify({"ok": False, "error": str(exc), "code": exc.code}), exc.http_status
    if isinstance(exc, (IdentityMappingError, SharedIdentityError)):
        return jsonify(
            {"ok": False, "error": str(exc), "code": "identity_mapping_missing"}
        ), 409
    sqlstate = getattr(exc, "sqlstate", None) or getattr(
        getattr(exc, "diag", None), "sqlstate", None
    )
    if sqlstate in {"23505", "40001"}:
        return jsonify({
            "ok": False,
            "error": "数据已被其他操作更新，或幂等键对应了不同请求；请刷新后重试",
            "code": "valuation_tracker_conflict",
        }), 409
    log.exception("user-content operation failed")
    return jsonify({"ok": False, "error": "user-content operation failed"}), 500


# ── 独立 sentiment.db(情绪/事件/代理/专题);C1:research.db 仅【只读】ATTACH ──
SENTI_DB_PATH = RUNTIME_LAYOUT.data_root / "sentiment.db"


def senti_conn() -> Optional[sqlite3.Connection]:
    sentiment_is_postgresql = bool(
        AUTHORITY_MATRIX is not None
        and AUTHORITY_MATRIX.routes["sentiment_analytics"].backend
        is DataBackend.POSTGRESQL_PRODUCTION
    )
    if sentiment_is_postgresql:
        # The multi-million-row sentiment unit has a reviewed persistent,
        # PostgreSQL-derived compatibility projection.  Do not open the
        # retired sentiment.db baseline and do not route it through the
        # bounded in-memory adapter used by smaller units.
        return connect_domain_database(
            "sentiment_analytics",
            SENTI_DB_PATH,
            readonly=True,
        )
    if not SENTI_DB_PATH.exists():
        return None
    sentiment_uri = f"file:{SENTI_DB_PATH.resolve().as_posix()}"
    read_only_base = bool(
        app.config.get("HONGHU_READ_ONLY_CANDIDATE")
    )
    if read_only_base:
        sentiment_uri += "?mode=ro"
    conn = sqlite3.connect(sentiment_uri, uri=True)
    conn.row_factory = sqlite3.Row
    if SHARED_IDENTITY_READ_CACHE is not None:
        SHARED_IDENTITY_READ_CACHE.attach(conn)
    else:
        conn.execute(f"ATTACH DATABASE 'file:{DB_PATH.as_posix()}?mode=ro' AS research")
        for table in ("company", "company_industry", "industry"):
            conn.execute(
                f'CREATE TEMP VIEW "{table}" AS SELECT * FROM research."{table}"'
            )
    if read_only_base:
        conn.execute("PRAGMA query_only=ON")
    return conn


def _request_senti_connection() -> tuple[Optional[sqlite3.Connection], bool]:
    """Reuse the PostgreSQL-derived sentiment projection within one request."""

    if not has_request_context():
        return senti_conn(), True
    connection = getattr(g, _REQUEST_SENTI_DB_KEY, None)
    if connection is None:
        connection = senti_conn()
        if connection is not None:
            setattr(g, _REQUEST_SENTI_DB_KEY, connection)
    return connection, False


def senti_all(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn, owned = _request_senti_connection()
    if conn is None:
        return []
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
        return []
    finally:
        if owned:
            conn.close()


def senti_one(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    conn, owned = _request_senti_connection()
    if conn is None:
        return None
    try:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None
    except Exception:
        return None
    finally:
        if owned:
            conn.close()


def _senti_table_exists(name: str) -> bool:
    """只读检查 sentiment.db 对象是否存在，供 V2/legacy 兼容读取。"""
    if not name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return False
    row = senti_one(
        "SELECT 1 AS ok FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    )
    return bool(row)


# ── 全站导航壳(v4 参考体系:左侧图标轨 + 行业侧栏)──────
# endpoint → 一级板块 key(用于高亮当前 rail 图标)
_NAV_SECTION_BY_ENDPOINT = {
    "index": "intel",
    "hypotheses_index": "hyp", "researcher_profile": "hyp",
    "hypothesis_detail": "hyp", "hypothesis_new": "hyp", "hypothesis_edit": "hyp",
    "research_home": "lib", "industry_detail": "lib", "industry_companies": "lib",
    "industry_chain": "lib", "industry_valuation": "lib", "metric_detail": "lib",
    "theme_detail": "lib", "company_tag": "lib", "companies_index": "companies", "companies_search_api": "companies",
    "events_index": "events", "event_detail": "events",
    "dynamic_voices": "voices",
    "dynamic_news": "news",
    "ai_macro_chain": "chain",
    "tools_index": "tools",
    "lithium_calculator": "tools",
    "lithium_industry_comparison": "tools",
    "copper_calculator": "tools",
    "copper_industry_comparison": "tools",
    "battery_calculator": "tools",
    "battery_industry_comparison": "tools",
    "q_horizontal": "q5",
    "data_points_index": "data",
    "sources_index": "sources", "source_detail": "sources",
    "incremental_index": "incr",
    "audit_extraction": "audit",
    "dynamic_sentiment": "senti", "sentiment_monitor": "senti", "monitor3": "senti",
    "proxy_job": "senti", "chain_sentiment": "senti",
    "supplychain": "senti",
}

# 一级板块 → 视觉世界:这些归"动态情报/观点流"世界(蓝玻璃),其余归"深度研究"世界(浅色)
_DYNAMIC_SECTIONS = {"intel", "hyp", "voices", "news", "events", "senti"}


@app.context_processor
def inject_nav():
    """注入全站导航壳所需的轻量数据(侧栏行业列表 + 当前激活板块)。
    防御性:任何查询失败都不应阻断页面渲染。"""
    industries: List[Dict[str, Any]] = []
    try:
        industries = _industry_overview_rows(navigation_order=True)
    except Exception:
        try:
            industries = query_all(
                "SELECT id, name, tier, status FROM industry "
                "ORDER BY (status='深度跟踪') DESC, tier ASC, name ASC"
            )
        except Exception:
            industries = []
    active = _NAV_SECTION_BY_ENDPOINT.get(getattr(request, "endpoint", "") or "", "")
    # 三世界基调:情绪事件系统 → 高对比深色(senti);动态情报/观点流 → 蓝玻璃;深度研究 → 浅色漏斗
    world = "senti" if active == "senti" else ("dynamic" if active in _DYNAMIC_SECTIONS else "research")
    return {
        "nav_industries": industries,
        "nav_active": active,
        "nav_world": world,
        "nav_deep_count": sum(1 for i in industries if i.get("status") == "深度跟踪"),
    }


# ── Markdown 渲染 ─────────────────────────────────────
MD_EXTENSIONS = [
    "fenced_code",
    "tables",
    "toc",
    "attr_list",       # 支持 {#anchor} 锚点
    "footnotes",
    "sane_lists",
    "md_in_html",
    "admonition",
]


# 数据溯源行内语法:^src:42 → 可点击上标(JS 弹 trace modal)
# 抗 slop 工程防线:任何叙事性 md 中的数据/判断都应能 trace 回 source。
SRC_REF_RE = re.compile(r"\^src:(\d+)")


def render_markdown(text: str) -> str:
    """渲染 markdown → HTML。KaTeX 数学公式由前端 auto-render 负责。
    额外:
    - 把 `^src:N` 替换为可点击的溯源上标(由前端 trace modal 捕获)。
    - 把行业 Q-md 相对链接(如 `光模块_Q4_行业特征.md`)重写为同页 tab 锚点
      `#tab-Q4`,这样主文档内 "详见 [Q4](xxx_Q4_xxx.md)" 点击即切到对应 Q tab。
      渲染层处理,md 文件保持干净相对链接,所有行业自动生效。
    """
    html = md_lib.markdown(text, extensions=MD_EXTENSIONS, output_format="html5")
    html = SRC_REF_RE.sub(
        r'<sup class="src-ref" data-source-id="\1" tabindex="0" role="button" title="点击溯源 source #\1">[\1]</sup>',
        html,
    )
    # Q-md 相对链接 → 同页 tab 锚点(href="任意_Q<n>_任意.md" → "#tab-Q<n>")
    html = re.sub(
        r'href="[^"]*_(Q\d)_[^"]*\.md"',
        r'href="#tab-\1" class="q-tab-link" data-tab-target="\1"',
        html,
    )
    return html


def wrap_markdown_tables_for_scroll(html: str) -> str:
    """给已渲染 Markdown 的每张表增加独立、可键盘访问的滚动容器。"""
    return re.sub(
        r"(<table\b[^>]*>.*?</table>)",
        (
            '<div class="md-table-wrap" tabindex="0" role="region" '
            'aria-label="研究数据表横向滚动">\\1</div>'
        ),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def load_md(file_path: Path) -> Dict[str, Any]:
    """读 md 文件,解析 frontmatter + 渲染正文。
    返回 {meta: dict, html: str, raw: str, exists: bool}。
    """
    if not file_path.exists():
        return {"meta": {}, "html": "", "raw": "", "exists": False}
    try:
        post = frontmatter.load(str(file_path))
        return {
            "meta": dict(post.metadata),
            "html": render_markdown(post.content),
            "raw": post.content,
            "exists": True,
        }
    except Exception:
        log.error(f"load_md error {file_path}: {traceback.format_exc()}")
        return {"meta": {}, "html": "", "raw": "", "exists": False, "error": True}


def find_industry_md(industry_name: str, q: Optional[str] = None) -> Optional[Path]:
    """按行业名找 md 文件。
    主文档:docs/industries/<name>.md
    Q0-Q5 独立:docs/industries/<name>_Q0_历史发展.md 等
    """
    if q:
        dimensions = {
            item_q: short
            for item_q, short, _ in industry_q_dimensions(industry_name)
        }
        short = dimensions.get(str(q).upper())
        if not short:
            return None
        candidate = (
            DOCS_DIR / "industries" / f"{industry_name}_{str(q).upper()}_{short}.md"
        )
        if not candidate.exists():
            matches = sorted(
                (DOCS_DIR / "industries").glob(
                    f"{industry_name}_{str(q).upper()}_*.md"
                )
            )
            candidate = matches[0] if len(matches) == 1 else candidate
    else:
        candidate = DOCS_DIR / "industries" / f"{industry_name}.md"
    return candidate if candidate.exists() else None


# ── Q5 综述 hero 解析(首页用,任务 5c)──────────────
Q5_HERO_SECTIONS = ("一句话核心判断", "三大支撑", "三大风险")


def parse_q5_hero(raw_md: str) -> Dict[str, Any]:
    """从 Q5 综述 md 的「核心判断(摘要)」节抽取 hero 展示内容。

    当前 Q5 结构(改动5):核心判断节由若干 `**结论X:<标题>。**` 粗体结论组成,
    每条后跟展开段落。hero 抽取:
      - 引导句(blockquote `> 一句话:...`,可选)
      - conclusions:每条结论的标题行(去 ^src,纯文本)

    向后兼容:若找不到结论,回退到旧的"一句话核心判断/三大支撑/三大风险"。
    """
    result: Dict[str, Any] = {
        "core_judgment": "",
        "conclusions": [],
        "supports": [],
        "risks": [],
        "has_any": False,
    }
    if not raw_md:
        return result

    # 切片 H2/H3 sections
    sections: Dict[str, str] = {}
    cur_title: Optional[str] = None
    cur_buf: List[str] = []
    for line in raw_md.splitlines():
        m = re.match(r"^\s*#{1,3}\s+(.+?)\s*$", line)
        if m:
            if cur_title is not None:
                sections[cur_title] = "\n".join(cur_buf).strip()
            cur_title = m.group(1).strip()
            cur_buf = []
        else:
            if cur_title is not None:
                cur_buf.append(line)
    if cur_title is not None:
        sections[cur_title] = "\n".join(cur_buf).strip()

    def clean_text(text: str) -> str:
        text = SRC_REF_RE.sub("", text or "")
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"\[(.*?)\]\([^)]+\)", r"\1", text)
        return re.sub(r"\s+", " ", text).strip()

    def strip_display_prefix(text: str) -> str:
        text = clean_text(text)
        text = re.sub(r"^\s*(?:#{1,6}\s*)?", "", text)
        text = re.sub(r"^\s*(?:第?[一二三四五六七八九十]+[、.．]|[一二三四五六七八九十]+、)\s*", "", text)
        text = re.sub(r"^\s*\d+(?:\.\d+)*[.．、]?\s*", "", text)
        text = re.sub(r"^(反方情景)[一二三四五六七八九十\d]+[：:]\s*", r"\1: ", text)
        text = re.sub(r"^(景气判断|格局判断|技术判断|风险判断|当前观点|综合判断|公司研究优先级|后续研究动作)[一二三四五六七八九十\d]*[：:]\s*", r"\1: ", text)
        text = re.sub(r"^(结论|判断)[：:]\s*", "", text)
        text = re.sub(r"^\s*(?:结论|判断)[一二三四五六七八九十\d]+[：:]\s*", "", text)
        return text.strip(" ：:。")

    def card_excerpt(text: str, limit: int) -> str:
        text = clean_text(text).strip(" ：:")
        if not text:
            return ""
        enum_items = re.findall(r"(?:第一|第二|第三|第四|第五)[，、:：]\s*([^。！？；;]+)", text)
        if enum_items and re.search(r"(?:主要有|有[一二三四五六七八九十\d]+类|有[一二三四五六七八九十\d]+个)", text):
            candidate = "；".join(strip_display_prefix(item) for item in enum_items[:2] if item.strip())
            if candidate:
                if len(candidate) <= limit:
                    return candidate
                return card_excerpt(candidate, limit)
        parts = re.findall(r"[^。！？；;]+[。！？；;]?", text)
        if parts:
            candidate = parts[0].strip()
            is_generic_lead = re.search(r"(?:主要有|有[一二三四五六七八九十\d]+类|有[一二三四五六七八九十\d]+个)", candidate)
            if len(candidate) <= limit and not is_generic_lead:
                return candidate.rstrip("；;")
        if "：" in text or ":" in text:
            sep = "：" if "：" in text else ":"
            head, rest = text.split(sep, 1)
            clauses = [c.strip() for c in re.split(r"[，,；;。！？]", rest) if c.strip()]
            for n in (2, 1):
                if clauses:
                    candidate = f"{head.strip()}{sep}{'，'.join(clauses[:n])}"
                    if len(candidate) <= limit:
                        return candidate
        short = re.split(r"[，,；;。！？]", text, 1)[0].strip()
        # “第一，……”这类长句不能在逗号回退时退化成孤立序号。
        ordinal_only = bool(re.fullmatch(
            r"(?:第?[一二三四五六七八九十]+|\d+(?:\.\d+)*)", short
        ))
        if short and len(short) <= limit and not ordinal_only:
            return short
        return text[: max(1, limit - 1)].rstrip("，,；;、 ：:") + "。"

    def conclusion_card_text(title: str, body: str = "") -> str:
        title_clean = strip_display_prefix(title)
        para = first_paragraph(body) if body else ""
        if para:
            # 首页卡片允许一条完整中文长句；54 字会让以“第一，”开头的
            # 73 字反方情景错误回退成“第一”。92 字可容纳该句而不堆正文。
            summary = card_excerpt(strip_display_prefix(para), 92)
            if title_clean in ("结论", "核心结论", "最终结论", "综合结论"):
                return summary or title_clean
            if title_clean and summary and title_clean not in summary:
                return f"{title_clean}: {summary}"
            return summary or title_clean
        return card_excerpt(title_clean, 66)

    def first_paragraph(body: str) -> str:
        buf: List[str] = []
        for raw in body.splitlines():
            line = raw.strip()
            if not line:
                if buf:
                    break
                continue
            # Markdown 粗体段落通常以 ``**`` 开头，它是正文而不是列表项。
            # 这里只跳过真正的 ``- ``/``* ``/``+ `` 列表，避免把“本章综述”
            # 中以粗体核心句开头的自然段误判为空。
            if (
                line.startswith(("|", "```", "- ", "* ", "+ "))
                or re.match(r"^\d+\.\s+", line)
            ):
                if buf:
                    break
                continue
            buf.append(line.lstrip("> ").strip())
        return clean_text(" ".join(buf))

    # 找“核心判断/最终判断/本章综述”节。新有色行业按统一写作合同把
    # 每章最重要的判断放在“本章综述”，不能因为标题不同就在首页丢失 Q5。
    summary_body = ""
    for title, body in sections.items():
        if any(k in title for k in (
            "核心判断", "最终判断", "核心结论", "综合判断", "本章综述",
        )):
            summary_body = body
            break

    if summary_body:
        # 引导句:blockquote `> 一句话:...`
        for raw in summary_body.splitlines():
            line = raw.strip()
            if line.startswith(">"):
                lead = line.lstrip("> ").strip()
                lead = re.sub(r"^一句话[：:]\s*", "", lead)
                lead = clean_text(lead)
                if lead:
                    result["core_judgment"] = card_excerpt(lead, 92)
                    break
        if not result["core_judgment"]:
            result["core_judgment"] = card_excerpt(first_paragraph(summary_body), 92)
        # 结论标题:`**结论X:<标题>**` 或 `**判断X:<标题>**`(只取粗体标题,不取展开段)
        # (存储 Q5 用"结论",大模型 Q5 用"判断",两者皆匹配)
        for raw in summary_body.splitlines():
            line = raw.strip()
            m = re.match(r"^\*\*((?:结论|判断)[一二三四五六七八九十\d]+[：:].+?)\*\*", line)
            if m:
                title_txt = conclusion_card_text(m.group(1))
                if title_txt:
                    result["conclusions"].append(title_txt)

    # “本章综述”通常是一段以粗体核心句开头的自然中文，而不是
    # `结论一：...` 这种旧格式。保留作者写好的完整句子，最多提取三条；
    # 这样首页卡片既有一句话判断，也确实显示“Q5 核心结论”。
    if summary_body and not result["conclusions"]:
        overview = first_paragraph(summary_body)
        for sentence in re.findall(r"[^。！？]+[。！？]?", overview):
            item = card_excerpt(sentence.strip(), 92)
            if item and item not in result["conclusions"]:
                result["conclusions"].append(item)
            if len(result["conclusions"]) >= 3:
                break

    # 新版 B 轨报告可把结构化结论分散在多个主线章节，而不另设一个
    # “核心判断”章节。全篇粗体结论是比标题关键词更可靠的语义合同；
    # 必须在启发式 fallback 前读取，并保留作者写好的完整结论标题。
    if not result["conclusions"]:
        seen_conclusions: set[str] = set()
        for raw in raw_md.splitlines():
            line = raw.strip()
            m = re.match(r"^\*\*((?:结论|判断)[一二三四五六七八九十\d]+[：:].+?)\*\*", line)
            if not m:
                continue
            title_txt = strip_display_prefix(m.group(1))
            if title_txt and title_txt not in seen_conclusions:
                seen_conclusions.add(title_txt)
                result["conclusions"].append(title_txt)

    if not result["conclusions"]:
        skip_words = ("综述", "深化研究", "来源权重", "相邻概念", "数据点", "反方必须", "计算过程", "时间有效性", "公司研报", "正文必须", "图表和正文", "最终核验")
        for title, body in sections.items():
            title_clean = strip_display_prefix(title)
            if not title_clean or any(w in title_clean for w in skip_words):
                continue
            if any(w in title_clean for w in ("核心判断", "最终判断", "核心结论")):
                continue
            if any(w in title_clean for w in ("景气判断", "格局判断", "技术判断", "风险判断", "当前观点", "综合判断", "结论", "公司研究优先级", "后续研究动作", "反方情景")):
                item = conclusion_card_text(title_clean, body)
                if item:
                    result["conclusions"].append(item)
            if len(result["conclusions"]) >= 4:
                break

    # 向后兼容旧结构
    if not result["conclusions"]:
        judg_body = sections.get("一句话核心判断", "")
        if judg_body and not result["core_judgment"]:
            first_para = judg_body.split("\n\n", 1)[0].strip()
            result["core_judgment"] = card_excerpt(first_para, 92)

        def extract_list_items(body: str, limit: int = 3) -> List[str]:
            items: List[str] = []
            for raw in body.splitlines():
                line = raw.strip()
                if line.startswith(("- ", "* ", "+ ")):
                    item = line[2:].strip()
                elif re.match(r"^\d+\.\s+", line):
                    item = re.sub(r"^\d+\.\s+", "", line).strip()
                else:
                    continue
                item = clean_text(item)
                if item:
                    items.append(item)
                if len(items) >= limit:
                    break
            return items
        result["supports"] = extract_list_items(sections.get("三大支撑", ""), 3)
        result["risks"]    = extract_list_items(sections.get("三大风险", ""), 3)

    result["has_any"] = bool(result["core_judgment"] or result["conclusions"]
                             or result["supports"] or result["risks"])
    return result


def load_q5_hero_for(industry_name: str) -> Dict[str, Any]:
    """读对应行业的 Q5 综述 md,parse 出 hero 三块。md 不存在则返回空 placeholder。"""
    p = find_industry_md(industry_name, "Q5")
    if not p:
        return {"core_judgment": "", "supports": [], "risks": [], "has_any": False, "has_md": False}
    doc = load_md(p)
    hero = parse_q5_hero(doc.get("raw") or "")
    hero["has_md"] = True
    hero["last_updated"] = doc["meta"].get("last_updated")
    return hero


# ── 路由:首页 dashboard ─────────────────────────────
@app.route("/")
def index():
    """动态情报首页(Stage 3-F cutover):今日要闻 + 未来 7 天事件 + 意见领袖 + 新闻流。
    数据为空显占位,不 mock。"""
    from datetime import date as _d, timedelta as _td
    import calendar as _calmod
    today = _d.today()
    # D1:今日要闻按 importance(B2 分级)取重要的;只 AI 相关。enrich → 行业 tag + when + is_gray
    headlines = [_enrich_news(h) for h in query_all("""
        SELECT n.*, s.source_credibility FROM news_item n LEFT JOIN source s ON s.id=n.source_id
        WHERE (n.is_ai_relevant=1 OR n.is_ai_relevant IS NULL)
          AND (n.is_breaking=1 OR n.importance<=2)
        ORDER BY n.is_breaking DESC, COALESCE(n.publish_date, n.fetch_timestamp) DESC, n.importance ASC LIMIT 8
    """)]
    ev7 = [_enrich_event(e) for e in query_all(
        "SELECT * FROM event WHERE scheduled_date BETWEEN ? AND ? AND status IN ('upcoming','confirmed') "
        "ORDER BY scheduled_date ASC, importance ASC LIMIT 8",
        (today.isoformat(), (today + _td(days=7)).isoformat()))]
    voices = query_all("""
        SELECT vp.content_text, vp.post_url, vp.posted_at, vp.post_type, ol.name AS leader_name,
               ol.platform, s.note AS leader_note
        FROM voice_post vp JOIN opinion_leader ol ON ol.id=vp.leader_id
        LEFT JOIN source s ON s.id=ol.source_id
        WHERE (vp.is_ai_relevant=1 OR vp.is_ai_relevant IS NULL)
          AND (vp.post_type IS NULL OR vp.post_type != '闲聊')
        ORDER BY vp.posted_at DESC LIMIT 16""")
    for v in voices:
        v["verified_kol"] = (v.get("leader_note") == "verified_kol")
    news = [_enrich_news(n) for n in query_all("""
        SELECT n.*, s.source_credibility FROM news_item n LEFT JOIN source s ON s.id=n.source_id
        WHERE (n.is_ai_relevant=1 OR n.is_ai_relevant IS NULL)
        ORDER BY n.is_breaking DESC, COALESCE(n.publish_date, n.fetch_timestamp) DESC, n.importance ASC LIMIT 10""")]
    totals = {
        "events": query_one("SELECT COUNT(*) AS n FROM event WHERE scheduled_date>=date('now')")["n"],
        "voices": query_one("SELECT COUNT(*) AS n FROM voice_post")["n"],
        "news": query_one("SELECT COUNT(*) AS n FROM news_item")["n"],
        "hyps": query_one("SELECT COUNT(*) AS n FROM hypothesis WHERE is_draft=0")["n"],
        "sentiment": ((senti_one("SELECT COUNT(DISTINCT company_id) AS n FROM senti_retail_daily") or {}).get("n") or 0),
    }
    # 联动:研究员观点(最新 5 条假说)
    hyp_latest = query_all("""
        SELECT h.id, h.title, h.thesis_type, h.status, h.created_at, h.last_updated_at,
               h.related_industry_ids, h.related_company_ids,
               r.display_name AS researcher_name, r.name AS researcher_raw, r.id AS researcher_id
        FROM hypothesis h JOIN researcher r ON r.id=h.researcher_id
        WHERE h.is_draft=0 ORDER BY COALESCE(h.last_updated_at, h.created_at) DESC LIMIT 5""")
    for h in hyp_latest:
        h["is_new"] = (not h.get("last_updated_at")) or ((h["last_updated_at"] or "")[:10] == (h["created_at"] or "")[:10])
        h["companies"], h["industries"] = _resolve_entity_names(
            h.get("related_company_ids"), h.get("related_industry_ids"))

    # 首页月历(真·日历):本月全部事件按日落格
    first = today.replace(day=1)
    last_day = _calmod.monthrange(today.year, today.month)[1]
    last = today.replace(day=last_day)
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for e in query_all(
        "SELECT id, title, scheduled_date, importance, event_type FROM event "
        "WHERE scheduled_date BETWEEN ? AND ? ORDER BY scheduled_date, importance",
        (first.isoformat(), last.isoformat())):
        by_day.setdefault((e.get("scheduled_date") or "")[:10], []).append(e)
    cal_grid = []
    for wk in _calmod.Calendar(firstweekday=0).monthdatescalendar(today.year, today.month):
        cal_grid.append([{
            "day": d.day, "in_month": (d.month == today.month),
            "is_today": (d == today), "events": by_day.get(d.isoformat(), []),
        } for d in wk])
    cal_month_label = "%d 年 %d 月" % (today.year, today.month)

    return render_template("dynamic_home.html", headlines=headlines, events=ev7,
                           voices=voices, news=news, totals=totals, hyp_latest=hyp_latest,
                           cal_grid=cal_grid, cal_month_label=cal_month_label)


@app.route("/dynamic_home")
def dynamic_home_redirect():
    return redirect(url_for("index"), code=301)


@app.route("/research")
def research_home():
    """行研库首页(原 / 内容,Stage 3-F cutover 迁到 /research)
    - Q5 综述 hero(核心判断 + 三大支撑 + 三大风险),来自第一个深度跟踪行业的 Q5 md
    - 深度内容入口卡(产业链 / 主文档 / 数据点 / Source 库)
    - 数据总览
    - 行业列表
    - active thesis 概览
    """
    industries = _industry_overview_rows()

    # 多行业 hero(UI 重设计):所有深度跟踪行业平等展示,各自 Q5 核心结论 + 入口
    # (替代原"只取首个深度行业"的硬编码;光模块不再独大)
    deep_cards: List[Dict[str, Any]] = []
    for ind in industries:
        if ind.get("status") != "深度跟踪":
            continue
        hero = load_q5_hero_for(ind["name"])
        # 读主 md frontmatter 的 data_tier_note(大模型 tier=3 诚实声明,用于卡片 banner)
        tier_note = ""
        main_p = find_industry_md(ind["name"])
        if main_p:
            tier_note = (load_md(main_p)["meta"].get("data_tier_note") or "")
        deep_cards.append({
            "id":               ind["id"],
            "name":             ind["name"],
            "tier":             ind.get("tier"),
            "core_dynamic":     ind.get("core_dynamic"),
            "last_updated":     hero.get("last_updated") or ind.get("last_updated"),
            "source_count":     ind.get("source_count"),
            "data_point_count": ind.get("data_point_count"),
            "company_count":    ind.get("company_count"),
            "core_judgment":    hero.get("core_judgment", ""),
            "conclusions":      hero.get("conclusions", []),
            "has_md":           hero.get("has_md", False),
            "data_tier_note":   tier_note,
        })
    first_deep = deep_cards[0] if deep_cards else None  # 向后兼容

    # 行研首页按“一级研究板块 → 细分行业”展示。板块是 Viewer 信息架构，
    # 不在 research.db 里制造没有研究正文的空行业。
    deep_by_name = {card["name"]: card for card in deep_cards}
    industry_by_name = {row["name"]: row for row in industries}
    sector_assignments = _derive_industry_group_assignments(
        industries,
        _RESEARCH_SECTORS,
    )
    sector_groups: List[Dict[str, Any]] = []
    assigned_names: set[str] = set()
    for sector_name, sector_cfg in _RESEARCH_SECTORS.items():
        explicit_names = [
            name for name in (sector_cfg.get("industries") or [])
            if name in industry_by_name
        ]
        inherited_names = sorted(
            name for name, assigned_sector in sector_assignments.items()
            if assigned_sector == sector_name
            and name in industry_by_name
            and name not in explicit_names
        )
        member_names = [*explicit_names, *inherited_names]
        assigned_names.update(member_names)
        sector_groups.append({
            "name": sector_name,
            "accent": sector_cfg.get("accent") or "#2563eb",
            "description": sector_cfg.get("description") or "",
            "deep_cards": [
                deep_by_name[name] for name in member_names if name in deep_by_name
            ],
            "supporting": [
                industry_by_name[name]
                for name in member_names
                if industry_by_name[name].get("status") != "深度跟踪"
            ],
        })
    unassigned_deep = [
        card for card in deep_cards if card["name"] not in assigned_names
    ]
    unassigned_supporting = [
        row for row in industries
        if row["name"] not in assigned_names
        and row.get("status") != "深度跟踪"
    ]
    if unassigned_deep or unassigned_supporting:
        sector_groups.append({
            "name": "其他研究",
            "accent": "#64748b",
            "description": "尚未归入上述一级板块的独立研究行业。",
            "deep_cards": unassigned_deep,
            "supporting": unassigned_supporting,
        })

    # active thesis
    active_theses = query_all("""
        SELECT t.*, i.name AS industry_name
        FROM thesis t LEFT JOIN industry i ON i.id = t.industry_id
        WHERE t.status='active' ORDER BY t.created_at DESC LIMIT 10
    """)

    # 总计
    totals = {
        "industries":      len(industries),
        "deep_industries": sum(1 for i in industries if i.get("status") == "深度跟踪"),
        "sources":         query_one("SELECT COUNT(*) AS n FROM source")["n"],
        "data_points":     query_one("SELECT COUNT(*) AS n FROM industry_data_point")["n"],
        "relations":       query_one("SELECT COUNT(*) AS n FROM industry_relation")["n"],
        "themes":          query_one("SELECT COUNT(*) AS n FROM theme")["n"],
        "companies":       query_one("SELECT COUNT(*) AS n FROM company")["n"],
        "active_theses":   len(active_theses),
    }

    # 待 review 的 md section 数(增量更新机制反查信号)
    pending_review = query_one(
        "SELECT COUNT(*) AS n FROM md_section_version WHERE review_pending=1"
    )
    totals["pending_review"] = pending_review["n"] if pending_review else 0

    return render_template(
        "dashboard.html",
        deep_cards=deep_cards,
        industries=industries,
        active_theses=active_theses,
        totals=totals,
        first_deep=first_deep,
        sector_groups=sector_groups,
    )


# ── 路由:行业详情页 ─────────────────────────────────
@app.route("/industry/<int:industry_id>")
def industry_detail(industry_id: int):
    ind = query_one("SELECT * FROM industry WHERE id=?", (industry_id,))
    if not ind:
        abort(404, f"industry id={industry_id} 不存在")

    # 主 md 文档
    main_md_path = find_industry_md(ind["name"])
    main_doc = load_md(main_md_path) if main_md_path else {"meta": {}, "html": "", "exists": False}

    # 行业维度独立 md；默认Q0-Q5，行业包可用小型manifest声明额外维度。
    q_dimensions = industry_q_dimensions(ind["name"])
    q_docs: Dict[str, Dict[str, Any]] = {}
    for q, _, _ in q_dimensions:
        p = find_industry_md(ind["name"], q)
        q_docs[q] = load_md(p) if p else {"meta": {}, "html": "", "exists": False}

    # 结构化数据 — data_points / relations / companies / sources
    data_points = query_all("""
        SELECT dp.*, s.title AS source_title, s.quality_tier AS source_tier
        FROM industry_data_point dp
        LEFT JOIN source s ON s.id = dp.source_id
        WHERE dp.industry_id=? ORDER BY dp.period DESC, dp.metric ASC
    """, (industry_id,))

    upstream = query_all("""
        SELECT r.*, i.name AS upstream_name, i.tier AS upstream_tier
        FROM industry_relation r JOIN industry i ON i.id = r.upstream_id
        WHERE r.downstream_id=? ORDER BY r.cost_share DESC NULLS LAST
    """, (industry_id,))
    downstream = query_all("""
        SELECT r.*, i.name AS downstream_name, i.tier AS downstream_tier
        FROM industry_relation r JOIN industry i ON i.id = r.downstream_id
        WHERE r.upstream_id=? ORDER BY r.demand_share DESC NULLS LAST
    """, (industry_id,))

    companies = query_all("""
        SELECT c.*, ci.role, ci.revenue_share
        FROM company_industry ci JOIN company c ON c.id = ci.company_id
        WHERE ci.industry_id=? ORDER BY ci.revenue_share DESC NULLS LAST
    """, (industry_id,))

    sources = query_all("""
        SELECT s.* FROM source_entity se JOIN source s ON s.id = se.source_id
        WHERE se.entity_type='industry' AND se.entity_id=?
        ORDER BY s.quality_tier ASC, s.publish_date DESC
    """, (str(industry_id),))

    theses = query_all("""
        SELECT * FROM thesis WHERE industry_id=? ORDER BY created_at DESC
    """, (industry_id,))

    # 增量状态(任务 6c):上次 review 时间 / 待 review section 数
    update_status = {
        "last_full_review": ind.get("last_updated"),
        "last_incremental": None,
        "pending_sections": 0,
    }
    last_snap = query_one(
        "SELECT snapshot_date FROM source_snapshot WHERE industry_id=? "
        "ORDER BY snapshot_date DESC LIMIT 1",
        (industry_id,),
    )
    if last_snap:
        update_status["last_incremental"] = last_snap.get("snapshot_date")
    pending = query_one(
        "SELECT COUNT(*) AS n FROM md_section_version "
        "WHERE review_pending=1 AND md_path LIKE ?",
        (f"%/industries/{ind['name']}%",),
    )
    if pending:
        update_status["pending_sections"] = pending["n"]

    # extraction_method 分布(本行业数据质量 banner 用)
    em_breakdown = {"pdf_direct": 0, "web_fetch": 0, "template_estimate": 0, "inferred": 0, "unknown": 0}
    for r in query_all("SELECT extraction_method, COUNT(*) c FROM industry_data_point WHERE industry_id=? GROUP BY extraction_method", (industry_id,)):
        em_breakdown[r["extraction_method"]] = r["c"]
    em_total = sum(em_breakdown.values())
    em_pct = {k: (100 * v // em_total if em_total else 0) for k, v in em_breakdown.items()}

    # 改动4:Q6 用户可编辑补充栏(<行业名>_Q6_补充.md)
    q6_path = DOCS_DIR / "industries" / f"{ind['name']}_Q6_补充.md"
    if q6_path.exists():
        q6_doc = load_md(q6_path)
    else:
        q6_doc = {"meta": {}, "html": "", "raw": "", "exists": False}

    # 2c-G:行业级 thesis(AI 散文式综合分析 + 研究员反共识)
    ind_thesis = query_one("SELECT * FROM industry_thesis WHERE industry_id=?", (industry_id,))
    consensus_html = ""
    if ind_thesis and ind_thesis.get("consensus_narrative"):
        consensus_html = render_markdown(ind_thesis["consensus_narrative"])
    if ind_thesis:
        ind_thesis["consensus_source_ids_list"] = _json_or([], ind_thesis.get("consensus_source_ids"))

    # 联动:本行业相关的研究员假说(related_industry_ids 含本 id;以人为标签)
    industry_hyps = []
    for h in query_all(
            "SELECT h.id, h.title, h.thesis_type, h.status, h.related_industry_ids, "
            "r.display_name AS researcher_name, r.name AS researcher_raw, r.id AS researcher_id "
            "FROM hypothesis h JOIN researcher r ON r.id=h.researcher_id "
            "WHERE h.is_draft=0 AND h.related_industry_ids LIKE ? "
            "ORDER BY COALESCE(h.last_updated_at, h.created_at) DESC", (f"%{industry_id}%",)):
        # LIKE 可能误匹配(如 id=9 命中 "19");精确校验 JSON 列表含本 id
        if industry_id in _as_id_list(h.get("related_industry_ids")):
            industry_hyps.append(h)
    industry_hyp_researchers = len({h["researcher_id"] for h in industry_hyps})

    # 结构化数据可视化(本行业):Top 指标 + 来源构成(Plotly,懒加载)
    ind_charts: Dict[str, str] = {}
    if _PLOTLY_OK and data_points:
        from collections import Counter as _Counter
        mc = _Counter(dp["metric"] for dp in data_points if dp.get("metric"))
        topm = mc.most_common(10)
        if topm:
            ind_charts["metrics"] = _hbar_div(
                [m for m, _ in topm], [n for _, n in topm], [str(n) for _, n in topm],
                color="#0d9488", height=max(150, 30 * len(topm) + 36))
        em_order = [("pdf_direct", "原文精读", "#16a34a"), ("web_fetch", "网搜", "#2563eb"),
                    ("inferred", "推算", "#0891b2"), ("template_estimate", "模板估(降级)", "#f59e0b"),
                    ("unknown", "未标", "#94a3b8")]
        trips = [(lab, em_breakdown.get(k, 0), col) for k, lab, col in em_order if em_breakdown.get(k, 0) > 0]
        trips.sort(key=lambda x: x[1], reverse=True)
        if trips:
            ind_charts["em"] = _hbar_div(
                [t[0] for t in trips], [t[1] for t in trips], [str(t[1]) for t in trips],
                colors=[t[2] for t in trips], height=max(140, 34 * len(trips) + 34))

    return render_template(
        "industry.html",
        ind=ind,
        ind_charts=ind_charts,
        industry_hyps=industry_hyps,
        industry_hyp_researchers=industry_hyp_researchers,
        main_doc=main_doc,
        q_docs=q_docs,
        q_dimensions=q_dimensions,
        has_static_q6=any(q == "Q6" for q, _, _ in q_dimensions),
        ind_thesis=ind_thesis,
        consensus_html=consensus_html,
        data_points=data_points,
        upstream=upstream,
        downstream=downstream,
        companies=companies,
        sources=sources,
        theses=theses,
        update_status=update_status,
        em_breakdown=em_breakdown,
        em_total=em_total,
        em_pct=em_pct,
        q6_doc=q6_doc,
    )


# ── 路由:Q6 用户补充栏保存(改动4,通用化 <industry_id>)──
@app.route("/industry/<int:industry_id>/q6/save", methods=["POST"])
def q6_save(industry_id: int):
    """接收 Q6 补充栏 md 文本,写入 <行业名>_Q6_补充.md。
    写前 backup 旧版到 cache/q6_backup_<ts>.md(防误删)。
    返回 JSON {ok, html}(html 为渲染后内容,前端直接刷新展示)。
    """
    ind = query_one("SELECT id, name FROM industry WHERE id=?", (industry_id,))
    if not ind:
        return {"ok": False, "error": f"industry id={industry_id} 不存在"}, 404
    md_text = (request.form.get("content") if request.form else None)
    if md_text is None:
        try:
            md_text = (request.get_json(silent=True) or {}).get("content", "")
        except Exception:
            md_text = ""
    md_text = md_text or ""

    q6_path = DOCS_DIR / "industries" / f"{ind['name']}_Q6_补充.md"
    # backup 旧版
    if q6_path.exists():
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bak_dir = ROOT / "cache"
            bak_dir.mkdir(parents=True, exist_ok=True)
            (bak_dir / f"q6_backup_{ind['name']}_{ts}.md").write_text(
                q6_path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            log.error(f"q6 backup error: {traceback.format_exc()}")

    # 若无 frontmatter,补一个最小 frontmatter(research_dimension: Q6)
    body = md_text
    if not md_text.lstrip().startswith("---"):
        fm = (f"---\nname: {ind['name']}\nresearch_dimension: Q6\n"
              f"author: zhengze\nlast_updated: {datetime.now().strftime('%Y-%m-%d')}\n---\n\n")
        body = fm + md_text

    try:
        q6_path.parent.mkdir(parents=True, exist_ok=True)
        q6_path.write_text(body, encoding="utf-8")
    except Exception:
        log.error(f"q6 save error: {traceback.format_exc()}")
        return {"ok": False, "error": "写入失败"}, 500

    # 渲染返回(用现有 render 管线,自动转义防 XSS)
    doc = load_md(q6_path)
    return {"ok": True, "html": doc.get("html", ""), "raw": doc.get("raw", "")}


# ── 路由:Q0-Q5 跨行业横向页 ──────────────────────────
@app.route("/q/<q>")
def q_horizontal(q: str):
    if q not in Q_TITLE_MAP:
        abort(404, f"研究维度仅支持 {', '.join(Q_TITLE_MAP.keys())}")
    q_title = Q_TITLE_MAP[q]
    industries = _industry_overview_rows(deep_only=True)
    docs = []
    for ind in industries:
        p = find_industry_md(ind["name"], q)
        if p:
            doc = load_md(p)
            docs.append({"industry": ind, "doc": doc, "has_md": True})
        else:
            docs.append({"industry": ind, "doc": {"meta": {}, "html": "", "exists": False}, "has_md": False})
    return render_template(
        "q_horizontal.html",
        q=q, q_title=q_title, q_short=Q_SHORT_MAP[q], docs=docs
    )


# 向后兼容:旧 /liang/<q> 链接 → 转 /q/<q>
@app.route("/liang/<q>")
def liang_horizontal_compat(q: str):
    if q in Q_TITLE_MAP:
        return redirect(url_for("q_horizontal", q=q), code=301)
    abort(404)


# ── 路由:产业链全景页 ───────────────────────────────
@app.route("/chain/<int:industry_id>")
def industry_chain(industry_id: int):
    """以某行业为中心,画上下游全景。
    阶段 1:简单表格 + 文字列表;后续可接 mermaid / d3。
    """
    center = query_one("SELECT * FROM industry WHERE id=?", (industry_id,))
    if not center:
        abort(404)

    upstream = query_all("""
        SELECT r.*, i.name AS node_name, i.id AS node_id, i.tier
        FROM industry_relation r JOIN industry i ON i.id = r.upstream_id
        WHERE r.downstream_id=?
    """, (industry_id,))
    downstream = query_all("""
        SELECT r.*, i.name AS node_name, i.id AS node_id, i.tier
        FROM industry_relation r JOIN industry i ON i.id = r.downstream_id
        WHERE r.upstream_id=?
    """, (industry_id,))

    # 可交互网络图(本节点居中 · 上游左 · 下游右)
    chain_net = ""
    if _PLOTLY_OK:
        def _spread(n):
            if n <= 0:
                return []
            if n == 1:
                return [0.0]
            span = min(2.4, 0.85 * (n - 1))
            return [span / 2 - span * i / (n - 1) for i in range(n)]
        uy, dy = _spread(len(upstream)), _spread(len(downstream))
        nodes = [{"x": 0, "y": 0, "label": center["name"], "color": "#0d9488", "size": 50,
                  "hover": center["name"] + "<br>本节点(tier " + str(center.get("tier") or "—") + ")",
                  "url": url_for("industry_detail", industry_id=center["id"])}]
        for k, u in enumerate(upstream):
            bp = (" · " + t(u["bargaining_power"])) if u.get("bargaining_power") else ""
            nodes.append({"x": -1.4, "y": uy[k], "label": u["node_name"], "color": "#2563eb", "size": 36,
                          "hover": u["node_name"] + "<br>上游 · " + (u.get("relation_type") or "关系") + bp,
                          "url": url_for("industry_detail", industry_id=u["node_id"])})
        for k, d in enumerate(downstream):
            bp = (" · " + t(d["bargaining_power"])) if d.get("bargaining_power") else ""
            nodes.append({"x": 1.4, "y": dy[k], "label": d["node_name"], "color": "#0891b2", "size": 36,
                          "hover": d["node_name"] + "<br>下游 · " + (d.get("relation_type") or "关系") + bp,
                          "url": url_for("industry_detail", industry_id=d["node_id"])})
        U = len(upstream)
        edges = [(1 + i, 0) for i in range(U)] + [(0, 1 + U + i) for i in range(len(downstream))]
        top = max((uy + dy) or [0]) + 0.7
        annotations = [dict(x=-1.4, y=top, text="上游", showarrow=False, font=dict(size=12, color="#94a3b8")),
                       dict(x=0, y=top, text="本节点", showarrow=False, font=dict(size=12, color="#94a3b8")),
                       dict(x=1.4, y=top, text="下游", showarrow=False, font=dict(size=12, color="#94a3b8"))]
        h = max(300, 92 * max(len(upstream), len(downstream), 1) + 120)
        chain_net = _network_div(nodes, edges, height=h, annotations=annotations)

    return render_template(
        "industry_chain.html",
        center=center, upstream=upstream, downstream=downstream,
        chain_net=chain_net,
    )


# ── 路由:跨板块产业链全景；保留 /ai-chain 兼容旧书签 ─────
@app.route("/industry-chain")
@app.route("/ai-chain")
def ai_macro_chain():
    """跨板块产业链：AI 算力与半导体 + 有色金属与新能源材料。"""
    industry_rows = [
        dict(row)
        for row in query_all("SELECT id, name, parent_id, tier, status FROM industry")
    ]
    all_rels = [dict(row) for row in query_all("""
        SELECT r.*, u.name AS up_name, d.name AS down_name
        FROM industry_relation r
        JOIN industry u ON u.id = r.upstream_id
        JOIN industry d ON d.id = r.downstream_id
        ORDER BY r.id
    """)]
    sector_assignments = _derive_industry_group_assignments(
        industry_rows,
        _RESEARCH_SECTORS,
    )
    ai_sector_name = "AI算力与半导体产业链"
    metal_sector_name = "有色金属与新能源材料"
    direction_configs = {
        str(direction.get("name")): direction
        for direction in _AI_CHAIN_DIRECTIONS
        if str(direction.get("name") or "").strip()
    }
    eligible_ai_names = {
        name for name, sector_name in sector_assignments.items()
        if sector_name == ai_sector_name
    }
    eligible_ai_names.update(
        name
        for direction in _AI_CHAIN_DIRECTIONS
        for name in (direction.get("industries") or [])
    )
    direction_assignments = _derive_industry_group_assignments(
        industry_rows,
        direction_configs,
        relations=all_rels,
        eligible_names=eligible_ai_names,
        minimum_relation_votes=2,
    )
    configured_names = set(sector_assignments) | set(direction_assignments)
    # industry_id=11 是旧书签和历史关系使用的稳定身份。数据库迁移前仍
    # 可能叫“云服务器厂商”，公开页先按准确语义展示为“云计算与算力运营”。
    # 迁移完成后名称自然一致，行业 id 和旧链接始终不变。
    covered: Dict[str, Dict[str, Any]] = {}
    for row in industry_rows:
        row = dict(row)
        public_name = (
            "云计算与算力运营"
            if int(row["id"]) == 11 and row["name"] == "云服务器厂商"
            else row["name"]
        )
        if configured_names and public_name not in configured_names:
            continue
        row["name"] = public_name
        covered[public_name] = row
    cross_rels = []
    for row in all_rels:
        public_row = dict(row)
        if int(public_row["upstream_id"]) == 11:
            public_row["up_name"] = "云计算与算力运营"
        if int(public_row["downstream_id"]) == 11:
            public_row["down_name"] = "云计算与算力运营"
        if public_row["up_name"] not in covered or public_row["down_name"] not in covered:
            continue
        # 旧关系记录的 note 中有少量构建批次标签和机器字段名。数据库原始
        # 事实保持不变，产业链公开页只做可读化，避免把内部 run tag 当正文。
        public_note = str(public_row.get("note") or "")
        public_note = re.sub(r"\bPCB_B_TRACK_\d{8}\s*:\s*", "", public_note)
        public_note = re.sub(
            r"\bCAGR_2020_2024\s*=\s*([0-9.]+%)",
            r"2020—2024年复合增速为\1",
            public_note,
        )
        public_row["note"] = public_note
        cross_rels.append(public_row)
    # 关键路径数据标注 — 只取 db 现有 dp(带 source_id 可溯源,绝不编造)
    # 每项指定 (展示标签, industry_id, metric, 可选 as_of 过滤),取最新一条
    fact_specs = [
        ("终端需求 · 九大 CSP 2026E 资本开支", 7, "CSP资本支出(亿美元)", "2026E"),
        ("存储 · HBM 2030E 市场规模",        7, "HBM_TAM_USD",          "2030-12-31"),
        ("存储 · AI 服务器存储用量倍数",      7, "AI服务器存储用量倍数",   None),
        ("大模型 · 中国日均 token 调用",      8, "token调用量(万亿/日)",  "2026-03"),
        ("通信 · 北美 CSP 2026 资本开支",     6, "北美四大云厂合计资本开支", "2026"),
        ("液冷 · 中国液冷服务器市场",         12, "中国液冷服务器市场规模(亿美元)", "2024"),
        ("AI服务器 · 全球市场规模",           15, "全球AI服务器市场规模", None),
    ]
    key_facts = []
    for label, iid, metric, aof in fact_specs:
        sql = ("SELECT value_num, value_text, unit, as_of_date, source_id, consensus_status "
               "FROM industry_data_point WHERE industry_id=? AND metric=?")
        params = [iid, metric]
        if aof:
            sql += " AND as_of_date LIKE ?"; params.append(aof + "%")
        sql += " ORDER BY as_of_date DESC LIMIT 1"
        row = query_one(sql, tuple(params))
        if row:
            val = (("%g" % row["value_num"]) if row["value_num"] is not None else (row["value_text"] or ""))
            key_facts.append({
                "label": label,
                "value": val + (row["unit"] or ""),
                "as_of": row["as_of_date"], "source_id": row["source_id"],
                "consensus": row["consensus_status"],
            })
    # ── 可交互产业链网络图(Plotly,semi 风格分层网络)──
    # 节点位置手工布局(AI 大产业已知四层结构);颜色=覆盖状态;customdata=url 点击跳转。
    TEAL, BLUE, GRAY, AMBER = "#0d9488", "#2563eb", "#94a3b8", "#f59e0b"

    _det = lambda i: url_for("industry_detail", industry_id=i)

    ai_names = {
        name for name, sector_name in sector_assignments.items()
        if sector_name == ai_sector_name
    } | set(direction_assignments)
    metal_names = {
        name for name, sector_name in sector_assignments.items()
        if sector_name == metal_sector_name
    }

    def _covered_node(
        name: str,
        x: float,
        y: float,
        size: int = 36,
        color: str | None = None,
        direction: str | None = None,
    ) -> Dict[str, Any]:
        row = covered.get(name)
        status = (row or {}).get("status")
        node_color = color if row and color else TEAL if status == "深度跟踪" else BLUE if row else GRAY
        state = status or "暂未覆盖"
        direction_text = f"<br>{direction}" if direction else ""
        return {
            "x": x, "y": y, "label": name, "color": node_color, "size": size,
            "symbol": "circle" if status == "深度跟踪" else "diamond" if row else "circle-open",
            "hover": (
                f"{name}{direction_text}<br>{state}；点击进入行业详情"
                if row else f"{name}{direction_text}<br>迁移尚未应用"
            ),
            "url": _det(row["id"]) if row else "",
        }

    chain_directions = []
    for direction in _AI_CHAIN_DIRECTIONS:
        direction_name = str(direction.get("name") or "")
        explicit_names = [
            name for name in (direction.get("industries") or [])
            if name in covered
        ]
        inferred_names = sorted(
            name for name, assigned_direction in direction_assignments.items()
            if assigned_direction == direction_name
            and name in covered
            and name not in explicit_names
        )
        chain_directions.append({
            **direction,
            "industries": [*explicit_names, *inferred_names],
        })
    chain_directions = chain_directions or [
        {"name": "算力生成", "color": BLUE, "industries": ["半导体设备", "算力芯片", "存储", "AI服务器"]},
        {"name": "数据搬运", "color": TEAL, "industries": ["通信", "光模块", "PCB制造"]},
        {"name": "物理承载", "color": "#7c3aed", "industries": ["液冷"]},
        {"name": "能源供给", "color": AMBER, "industries": ["电力"]},
        {"name": "软件变现", "color": "#db2777", "industries": ["云计算与算力运营", "大模型", "AI应用"]},
    ]
    lane_count = len(chain_directions)
    max_lane_nodes = max(
        (len(direction.get("industries") or []) for direction in chain_directions),
        default=1,
    )
    lane_x = [
        index - (lane_count - 1) / 2
        for index in range(lane_count)
    ]
    ai_nodes: List[Dict[str, Any]] = []
    for lane_index, direction in enumerate(chain_directions):
        industries = list(direction.get("industries") or [])
        for row_index, name in enumerate(industries):
            size = 42 if name in {"算力芯片", "AI服务器", "光模块", "云计算与算力运营", "AI应用"} else 34
            ai_nodes.append(
                _covered_node(
                    name,
                    lane_x[lane_index],
                    max_lane_nodes - row_index - 1,
                    size,
                    str(direction.get("color") or BLUE),
                    str(direction.get("name") or ""),
                )
            )
    ai_index = {node["label"]: idx for idx, node in enumerate(ai_nodes)}
    ai_edges = {
        (ai_index[row["up_name"]], ai_index[row["down_name"]])
        for row in cross_rels
        if row["up_name"] in ai_index and row["down_name"] in ai_index
    }
    # Viewer 层级关系只补充价值链阅读路径，不作为量化供需证据。
    for upstream, downstream in (
        ("半导体设备", "算力芯片"),
        ("存储", "内存与高速互连芯片"),
        ("算力芯片", "AI服务器"),
        ("内存与高速互连芯片", "AI服务器"),
        ("AI服务器", "机架级系统集成"),
        ("低损耗覆铜板与电子材料", "PCB制造"),
        ("PCB制造", "高多层PCB板"),
        ("高多层PCB板", "AI服务器"),
        ("光模块", "通信"),
        ("高速铜互连", "AI服务器"),
        ("通信", "云计算与算力运营"),
        ("数据中心供电", "数据中心建设与运营"),
        ("电力", "数据中心建设与运营"),
        ("液冷", "数据中心建设与运营"),
        ("数据中心建设与运营", "云计算与算力运营"),
        ("机架级系统集成", "云计算与算力运营"),
        ("云计算与算力运营", "大模型"),
        ("大模型", "AI应用"),
        ("AI应用", "办公与文档智能"),
        ("AI应用", "金融知识与决策"),
        ("AI应用", "教育医疗与公共服务"),
        ("AI应用", "企业管理与工业流程"),
        ("AI应用", "网络安全与IT运营"),
        ("智能终端与物理AI", "机器人与工业智能"),
    ):
        if upstream in ai_index and downstream in ai_index:
            ai_edges.add((ai_index[upstream], ai_index[downstream]))
    ai_shapes = [
        dict(
            type="rect", xref="x", yref="y",
            x0=x - 0.46, x1=x + 0.46,
            y0=-0.55, y1=max_lane_nodes - 0.15,
            fillcolor=("rgba(15,23,42,0.025)" if index % 2 == 0 else "rgba(15,23,42,0.045)"),
            line=dict(color="rgba(148,163,184,0.18)", width=1), layer="below",
        )
        for index, x in enumerate(lane_x)
    ]
    ai_annotations = [
        dict(
            x=lane_x[index], y=max_lane_nodes + 0.10,
            xref="x", yref="y",
            text=f"<b>{direction.get('name', '')}</b>",
            showarrow=False, xanchor="center", align="center",
            font=dict(size=12, color=str(direction.get("color") or "#334155")),
        )
        for index, direction in enumerate(chain_directions)
    ]
    chain_net = _network_div(
        ai_nodes, sorted(ai_edges), height=max(650, 60 * max_lane_nodes + 80),
        shapes=ai_shapes, annotations=ai_annotations,
    )

    metal_nodes: List[Dict[str, Any]] = [
        {
            "x": 0, "y": 3, "label": "能源转型与基础设施需求",
            "color": AMBER, "size": 46,
            "hover": "需求观察层：电网、数据中心、电动车与储能<br>用于组织研究，不是独立行业记录",
            "url": "",
        },
        _covered_node("铜", -1.25, 2, 44),
        _covered_node("锂", 1.25, 2, 44),
        _covered_node("碳酸锂", 1.25, 1, 40),
        _covered_node("锂电池", 1.25, 0, 42),
    ]
    metal_edges = [(0, 1), (0, 2), (2, 3), (3, 4)]
    metal_layers = [
        (3, "① 共同需求"),
        (2, "② 资源行业"),
        (1, "③ 加工与材料"),
        (0, "④ 电池产品"),
    ]
    metal_shapes = [
        dict(
            type="rect", xref="x", yref="y",
            x0=-2.1, x1=2.1, y0=y - 0.40, y1=y + 0.40,
            fillcolor=("rgba(180,83,9,0.055)" if i % 2 == 0 else "rgba(217,119,6,0.035)"),
            line=dict(width=0), layer="below",
        )
        for i, (y, _) in enumerate(metal_layers)
    ]
    metal_annotations = [
        dict(
            x=-2.02, y=y, xref="x", yref="y", text=label,
            showarrow=False, xanchor="left",
            font=dict(size=11, color="#78716c"),
        )
        for y, label in metal_layers
    ]
    metals_chain_net = _network_div(
        metal_nodes, metal_edges, height=500,
        shapes=metal_shapes, annotations=metal_annotations,
    )
    ai_covered = {
        name: row for name, row in covered.items() if name in ai_names
    }
    metals_covered = {
        name: row for name, row in covered.items() if name in metal_names
    }

    return render_template(
        "macro_chain.html",
        covered=covered,
        ai_covered=ai_covered,
        metals_covered=metals_covered,
        cross_rels=cross_rels,
        key_facts=key_facts,
        ai_chain_directions=chain_directions,
        chain_net=chain_net,
        metals_chain_net=metals_chain_net,
    )


# ── 路由:Source 详情页 ──────────────────────────────
@app.route("/source/<int:source_id>")
def source_detail(source_id: int):
    src = query_one("SELECT * FROM source WHERE id=?", (source_id,))
    if not src:
        abort(404)
    # key_arguments 是 JSON 数组,解析为列表
    key_args: List[str] = []
    if src.get("key_arguments"):
        try:
            parsed = json.loads(src["key_arguments"])
            if isinstance(parsed, list):
                key_args = [str(x) for x in parsed]
        except Exception:
            log.warning(f"source #{source_id} key_arguments not JSON: {src['key_arguments'][:80]}")

    entities = query_all("""
        SELECT * FROM source_entity WHERE source_id=?
    """, (source_id,))
    enriched = []
    for e in entities:
        name = None
        if e["entity_type"] == "industry":
            row = query_one("SELECT name FROM industry WHERE id=?", (int(e["entity_id"]),))
            name = row["name"] if row else None
        elif e["entity_type"] == "company":
            row = query_one("SELECT name FROM company WHERE id=?", (int(e["entity_id"]),))
            name = row["name"] if row else None
        elif e["entity_type"] == "theme":
            row = query_one("SELECT name FROM theme WHERE id=?", (e["entity_id"],))
            name = row["name"] if row else None
        e["entity_name"] = name
        enriched.append(e)

    data_points = query_all("""
        SELECT dp.*, i.name AS industry_name
        FROM industry_data_point dp LEFT JOIN industry i ON i.id = dp.industry_id
        WHERE dp.source_id=? ORDER BY dp.metric
    """, (source_id,))

    return render_template(
        "source.html",
        src=src, entities=enriched, data_points=data_points, key_args=key_args,
    )


# ── 路由:公司 tag 页(极简)─────────────────────────
@app.template_filter("fnum")
def _fnum(v, nd=1):
    """安全数字格式化:可转 float 则按位数,否则原样返回(profile 部分字段是字符串)。"""
    try:
        return f"{float(v):.{int(nd)}f}"
    except (TypeError, ValueError):
        return v


COMPANY_CORE_METRICS = (
    {
        "key": "pe_ttm", "label": "PE (TTM)", "kind": "multiple",
        "formula": "市盈率 = 股价 / 过去 12 个月每股收益",
        "as_of": "valuation_as_of", "source": "valuation_source_id",
    },
    {
        "key": "pb", "label": "PB", "kind": "multiple",
        "formula": "市净率 = 股价 / 每股净资产",
        "as_of": "valuation_as_of", "source": "valuation_source_id",
    },
    {
        "key": "roe", "label": "ROE", "kind": "percent",
        "formula": "净资产收益率 = 归母净利润 / 平均归母净资产",
        "as_of": "financial_metrics_as_of", "source": "financial_metrics_source_id",
    },
    {
        "key": "roa", "label": "ROA", "kind": "percent",
        "formula": "总资产收益率 = 净利润 / 平均总资产",
        "as_of": "financial_metrics_as_of", "source": "financial_metrics_source_id",
    },
    {
        "key": "eps_ttm", "label": "EPS (TTM)", "kind": "per_share",
        "formula": "每股收益 = 过去 12 个月归母净利润 / 加权平均普通股数",
        "as_of": "financial_metrics_as_of", "source": "financial_metrics_source_id",
    },
    {
        "key": "bps_mrq", "label": "BPS (MRQ)", "kind": "per_share",
        "formula": "每股净资产 = 期末归母股东权益 / 期末普通股数",
        "as_of": "financial_metrics_as_of", "source": "financial_metrics_source_id",
    },
)


def _metric_number(value, kind: str, currency: Optional[str] = None) -> Optional[str]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return None
    if kind == "percent":
        return f"{number:.2f}%"
    if kind == "multiple":
        return f"{number:.2f}×"
    if kind == "per_share":
        suffix = f" {currency}/股" if currency else "/股"
        return f"{number:.2f}{suffix}"
    return f"{number:,.2f}"


def _per_share_currency_from_unit(value: Any) -> Optional[str]:
    unit = str(value or "").strip()
    iso_per_share = re.fullmatch(
        r"(CNY|HKD|USD|JPY|EUR)/(?:股|SHARE)", unit.upper(),
    )
    if iso_per_share:
        return iso_per_share.group(1)
    if "港元" in unit:
        return "HKD"
    if "美元" in unit:
        return "USD"
    if "日元" in unit:
        return "JPY"
    if "欧元" in unit:
        return "EUR"
    if "元/股" in unit:
        return "CNY"
    return None


def _positive_pe(value: Any) -> bool:
    """PE 只有有限正数才可用于展示、排序和覆盖度统计。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _company_metric_cards(
    co: Dict[str, Any],
    profile: Optional[Dict[str, Any]] = None,
    *,
    strict_financial_source: bool = False,
    financial_bundle: Optional[Dict[str, Any]] = None,
) -> list:
    """六项核心指标只读 financial.db；Wind 有效值优先、Tushare 逐字段补缺。"""
    profile = profile or {}
    unlisted = (co.get("listing_status") in UNLISTED_LISTING_STATUSES) or not co.get("ticker")
    # 每股指标只能使用明确的每股币种；market_cap_unit 可能是“亿元人民币”，
    # 不能把市值单位错误拼成“亿元人民币/股”。
    current_metrics = (financial_bundle or {}).get("current_metrics") or {}
    if financial_bundle is not None:
        currency = _per_share_currency_from_unit(
            (current_metrics.get("eps_ttm") or {}).get("unit")
            or (current_metrics.get("bps_mrq") or {}).get("unit")
        )
    else:
        currency = co.get("per_share_currency")
    cards = []
    missing_reason = (
        profile.get("_financial_absence_reason")
        or (
            "当前结构化数据源未返回该字段"
            if financial_bundle is not None
            else "尚未建立结构化财务画像"
        )
    )
    for meta in COMPANY_CORE_METRICS:
        source_row = current_metrics.get(meta["key"])
        use_legacy_compat = financial_bundle is None and not strict_financial_source
        value = (
            source_row.get("value_num")
            if source_row
            else co.get(meta["key"]) if use_legacy_compat else None
        )
        reason = None
        if meta["key"] == "pe_ttm":
            if value is not None and not _positive_pe(value):
                try:
                    pe_number = float(value)
                except (TypeError, ValueError):
                    pe_number = math.nan
                value = None
                reason = (
                    "亏损/PE不适用"
                    if math.isfinite(pe_number) and pe_number <= 0
                    else missing_reason
                )
            elif value is None:
                # 数据源通常会对亏损公司直接省略 PE。此时负/零 EPS 已足以证明
                # PE 不适用，不能误报成“接口没抓到”；不使用 ROE 反推盈利状态。
                try:
                    eps_row = current_metrics.get("eps_ttm") or {}
                    eps_number = float(
                        eps_row.get("value_num")
                        if eps_row.get("value_num") is not None
                        else co.get("eps_ttm") if use_legacy_compat else None
                    )
                except (TypeError, ValueError):
                    eps_number = math.nan
                if math.isfinite(eps_number) and eps_number <= 0:
                    reason = "亏损/PE不适用"
        elif (
            meta["key"] == "bps_mrq"
            and value is None
            and "股本口径" in str(profile.get("display_note") or "")
        ):
            reason = "股本口径对账未通过，暂不展示"
        display = _metric_number(value, meta["kind"], currency)
        if display is None and reason is None:
            reason = "未上市 / 不适用" if unlisted else missing_reason
        as_of = (
            source_row.get("as_of_date")
            if source_row
            else co.get(meta["as_of"]) if use_legacy_compat else None
        )
        legacy_source_id = co.get(meta["source"]) if use_legacy_compat else None
        cards.append({**meta, "raw": value, "display": display, "reason": reason,
                      "as_of": as_of, "source_id": legacy_source_id,
                      "source_title": source_row.get("source_title") if source_row else None,
                      "source_ref": source_row.get("source_ref") if source_row else None,
                      "provider": source_row.get("provider") if source_row else None,
                      "provider_label": source_row.get("provider_label") if source_row else None,
                      "fact_type": source_row.get("fact_type") if source_row else "legacy_aggregate"})
    return cards


def _aligned_company_financial_rows(revenue: list, net_income: list) -> list[dict[str, Any]]:
    """Align revenue and net income by canonical period instead of list position."""
    def _key(row: Dict[str, Any]) -> str:
        return str(row.get("metric_period") or row.get("period") or "").strip()

    rmap = {_key(row): row for row in revenue or [] if _key(row)}
    nmap = {_key(row): row for row in net_income or [] if _key(row)}
    periods: list[str] = []
    for row in list(revenue or []) + list(net_income or []):
        key = _key(row)
        if key and key not in periods:
            periods.append(key)
    return [{
        "key": period,
        "period": (rmap.get(period) or nmap.get(period) or {}).get("period") or period,
        "revenue": rmap.get(period),
        "net_income": nmap.get(period),
    } for period in periods]


def _pcb_public_profile_note(note: Any) -> Optional[str]:
    """Expose only decision-useful company-specific caveats, never production coverage text."""
    text = str(note or "")
    bps = re.search(r"(?:当前)?BPS[^。]*股本口径[^。]*暂不展示BPS。?", text)
    return bps.group(0).strip() if bps else None


def _pcb_public_coverage_note(profile: Dict[str, Any]) -> Optional[str]:
    """Translate missing PCB P&L periods into one natural reader-facing consequence."""
    revenue = profile.get("revenue_series_list") or []
    net_income = profile.get("net_income_series_list") or []
    rows = _aligned_company_financial_rows(revenue, net_income)
    if not rows:
        if not profile.get("ticker") or profile.get("listing_status") in UNLISTED_LISTING_STATUSES:
            return None
        return "公开接口未返回2023—2025年及2026年一季度可展示损益，因此不参与最新增长比较。"
    complete = {
        row["key"]
        for row in rows
        if row.get("revenue") and row.get("net_income")
        and row["revenue"].get("value") is not None
        and row["net_income"].get("value") is not None
    }
    labels = {
        "2023": "2023年", "2024": "2024年", "2025": "2025年", "2026Q1": "2026年一季度",
    }
    missing = [key for key in labels if key not in complete]
    if not missing:
        return None
    missing_text = "、".join(labels[key] for key in missing)
    latest = str(profile.get("financials_as_of") or "").strip()
    latest_text = f"；目前最新完整展示期截至{latest[:10]}" if latest else ""
    return f"公开接口未返回{missing_text}可比损益{latest_text}，缺失期间不参与增长比较。"


def _pcb_public_recent_events(events: list) -> list[dict[str, Any]]:
    """Keep genuine dated corporate actions; hide research verification activity."""
    result: list[dict[str, Any]] = []
    for raw in events or []:
        if not isinstance(raw, dict):
            continue
        event = dict(raw)
        title = str(event.get("title") or "").strip()
        summary = str(event.get("summary") or "").strip()
        is_verification = title.startswith("官方资料核验：") or "官方资料核验" in summary or summary.startswith("本轮以")
        if is_verification:
            if not re.search(r"收购|出售", title):
                continue
            event["summary"] = ""
        result.append(event)
    return result


def _company_financial_figure(revenue: list, net_income: list) -> Optional[dict]:
    """营收/净利双轴趋势；数值口径不同也不强行归一，hover 保留原单位。"""
    def stable_unit(rows: list) -> str:
        if any(row.get("cny_yi") is not None for row in rows or []):
            return "亿元人民币"
        for row in rows or []:
            unit = str(row.get("unit") or "").strip()
            if unit:
                # 跨期图例只能展示稳定量纲，不能把某一期汇率折算金额当作序列单位。
                return re.sub(r"\s*[（(]\s*约?[^）)]*[）)]\s*$", "", unit).strip()
        return ""

    def hover_details(rows_by_period: dict, periods_: list, axis_unit: str) -> list[str]:
        details = []
        for period in periods_:
            row = rows_by_period.get(period, {})
            parts = []
            unit = str(row.get("unit") or "").strip()
            original = str(row.get("original_display") or "").strip()
            if unit and unit != axis_unit:
                parts.append(unit)
            if original and original not in parts:
                parts.append(f"原报表口径：{original}")
            details.append("；".join(parts))
        return details

    periods = []
    for row in list(revenue or []) + list(net_income or []):
        period = str(row.get("period") or "").strip()
        if period and period not in periods:
            periods.append(period)
    periods.sort()
    if len(periods) < 2:
        return None
    rmap = {str(r.get("period")): r for r in revenue or []}
    nmap = {str(r.get("period")): r for r in net_income or []}
    rvals = [rmap.get(p, {}).get("value") for p in periods]
    nvals = [nmap.get(p, {}).get("value") for p in periods]
    data = []
    if any(v is not None for v in rvals):
        runit = stable_unit(revenue)
        data.append({"type": "bar", "x": periods, "y": rvals,
                     "name": f"营收（{runit}）" if runit else "营收",
                     "customdata": hover_details(rmap, periods, runit),
                     "hovertemplate": f"%{{x}}<br>营收 %{{y:,.2f}} {runit}<br>%{{customdata}}<extra></extra>",
                     "marker": {"color": "rgba(36,112,184,.72)"}, "yaxis": "y"})
    if any(v is not None for v in nvals):
        nunit = stable_unit(net_income)
        data.append({"type": "scatter", "mode": "lines+markers", "x": periods, "y": nvals,
                     "name": f"净利润（{nunit}）" if nunit else "净利润",
                     "customdata": hover_details(nmap, periods, nunit),
                     "hovertemplate": f"%{{x}}<br>净利润 %{{y:,.2f}} {nunit}<br>%{{customdata}}<extra></extra>",
                     "line": {"color": "#d97706", "width": 3},
                     "marker": {"size": 7}, "yaxis": "y2"})
    if not data:
        return None
    return {
        "data": data,
        "layout": {
            "height": 330, "margin": {"l": 58, "r": 58, "t": 18, "b": 48},
            "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "#fbfdff",
            "hovermode": "x unified", "barmode": "group",
            "legend": {"orientation": "h", "x": 0, "y": 1.12},
            "xaxis": {"type": "category", "gridcolor": "#eef2f7"},
            "yaxis": {"title": f"营收（{stable_unit(revenue)}）" if stable_unit(revenue) else "营收",
                      "gridcolor": "#e8edf5", "zerolinecolor": "#cbd5e1"},
            "yaxis2": {"title": f"净利润（{stable_unit(net_income)}）" if stable_unit(net_income) else "净利润",
                       "overlaying": "y", "side": "right", "showgrid": False,
                       "zerolinecolor": "#cbd5e1"},
        },
    }


def _company_landscape_figures(profiles: list) -> dict:
    """公司透视页的份额与盈利结构图；无足够数据时返回 None，表格仍是完整 fallback。"""
    share_rows = [p for p in profiles if p.get("global_share") is not None or p.get("china_share") is not None]
    share_rows.sort(key=lambda p: max(p.get("global_share") or 0, p.get("china_share") or 0), reverse=True)
    share_rows = share_rows[:20]
    share_fig = None
    if len(share_rows) >= 2:
        share_fig = {"data": [
            {"type": "bar", "orientation": "h", "name": "全球份额", "y": [p["company_name"] for p in share_rows],
             "x": [p.get("global_share") for p in share_rows], "marker": {"color": "#2470b8"},
             "hovertemplate": "%{y}<br>全球份额 %{x:.2f}%<extra></extra>"},
            {"type": "bar", "orientation": "h", "name": "中国份额", "y": [p["company_name"] for p in share_rows],
             "x": [p.get("china_share") for p in share_rows], "marker": {"color": "#d97706"},
             "hovertemplate": "%{y}<br>中国份额 %{x:.2f}%<extra></extra>"},
        ], "layout": {
            "height": max(360, 32 * len(share_rows) + 100), "barmode": "group",
            "margin": {"l": 120, "r": 20, "t": 20, "b": 50},
            "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "#fbfdff",
            "legend": {"orientation": "h", "x": 0, "y": 1.1},
            "xaxis": {"title": "份额 (%)", "gridcolor": "#e8edf5", "rangemode": "tozero"},
            "yaxis": {"autorange": "reversed"},
        }}
    profit_rows = [p for p in profiles if p.get("gross_margin") is not None and p.get("net_margin") is not None]
    profit_fig = None
    if len(profit_rows) >= 2:
        caps = [max(float(p.get("market_cap_cny") or 0), 0) for p in profit_rows]
        cap_ref = max(caps) or 1
        profit_fig = {"data": [{
            "type": "scatter", "mode": "markers", "x": [p.get("gross_margin") for p in profit_rows],
            "y": [p.get("net_margin") for p in profit_rows], "text": [p["company_name"] for p in profit_rows],
            "customdata": [[p.get("ticker") or "—", p.get("financials_as_of") or "—"] for p in profit_rows],
            "marker": {"size": [max(9, min(34, 9 + 25 * math.sqrt(c / cap_ref))) if c else 9 for c in caps],
                       "color": [p.get("roe") for p in profit_rows], "colorscale": "Tealgrn", "showscale": True,
                       "colorbar": {"title": "ROE (%)"}, "opacity": .8, "line": {"color": "#fff", "width": 1}},
            "hovertemplate": "%{text}<br>代码 %{customdata[0]}<br>毛利率 %{x:.2f}%<br>净利率 %{y:.2f}%<br>财务期 %{customdata[1]}<extra></extra>",
        }], "layout": {
            "height": 410, "margin": {"l": 64, "r": 60, "t": 20, "b": 56},
            "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "#fbfdff",
            "xaxis": {"title": "毛利率 (%)", "gridcolor": "#e8edf5"},
            "yaxis": {"title": "净利率 (%)", "gridcolor": "#e8edf5", "zerolinecolor": "#cbd5e1"},
        }}
    return {"share": share_fig, "profitability": profit_fig}


def _asset_return_figures(bundle: dict[str, Any] | None) -> dict[str, Any]:
    """Build transparent PB-return charts; never fit when independent pairs are insufficient."""
    if not bundle:
        return {
            "pb_roe": None, "pb_roa": None, "pb_history": None,
            "pb_price_band": None, "pe_price_band": None, "roe_path": None,
            "pb_roe_model": None, "pb_roa_model": None,
            "pb_price_band_availability": None,
            "pe_price_band_availability": None,
        }
    asset = bundle.get("asset_return") or {}
    current = asset.get("current") or {}
    figures: dict[str, Any] = {}
    models: dict[str, Any] = {}
    for key, x_label, current_key in (
        ("pb_roe", "ROE (%)", "roe"),
        ("pb_roa", "ROA (%)", "roa"),
    ):
        points = list(asset.get(f"{key}_points") or [])
        rows = [{"period": p["period"], current_key: p["return_value"], "pb": p["pb"]} for p in points]
        model = None
        if len(rows) >= 3:
            try:
                current_value = float((current.get(current_key) or {}).get("value_num"))
                model = (
                    historical_pb_roe(rows, current_roe=current_value)
                    if current_key == "roe"
                    else historical_pb_roa(rows, current_roa=current_value)
                )
            except (TypeError, ValueError):
                model = None
        data: list[dict[str, Any]] = []
        if points:
            data.append({
                "type": "scatter", "mode": "markers+text",
                "x": [p["return_value"] for p in points], "y": [p["pb"] for p in points],
                "text": [p["period"] for p in points], "textposition": "top center",
                "name": "独立报告期配对点", "marker": {"size": 9, "color": "#2470b8"},
                "customdata": [[p["return_as_of"], p["pb_as_of"]] for p in points],
                "hovertemplate": f"%{{text}}<br>{x_label} %{{x:.2f}}<br>PB %{{y:.2f}}<br>财务期 %{{customdata[0]}}<br>PB时点 %{{customdata[1]}}<extra></extra>",
            })
        x_now = (current.get(current_key) or {}).get("value_num")
        y_now = (current.get("pb") or {}).get("value_num")
        if x_now is not None and y_now is not None:
            data.append({
                "type": "scatter", "mode": "markers", "x": [x_now], "y": [y_now],
                "name": "当前观察", "marker": {"size": 13, "color": "#c24130", "symbol": "diamond"},
                "hovertemplate": f"当前<br>{x_label} %{{x:.2f}}<br>PB %{{y:.2f}}<extra></extra>",
            })
        if model and points:
            model = dict(model)
            if y_now is not None:
                model["current_pb"] = float(y_now)
                model["current_residual"] = float(y_now) - float(model["reasonable_pb"])
                sigma = float(model.get("residual_sigma") or 0.0)
                if sigma > 0 and model.get("residual_space") == "ln(pb)" and float(y_now) > 0:
                    model["current_residual_sigma"] = (
                        math.log(float(y_now)) - math.log(float(model["reasonable_pb"]))
                    ) / sigma
                else:
                    model["current_residual_sigma"] = model["current_residual"] / sigma if sigma > 0 else None
            xs = sorted({float(p["return_value"]) for p in points} | ({float(x_now)} if x_now is not None else set()))
            residual_half_width = 1.96 * max(0.0, float(model["residual_sigma"]))
            is_log_pb = model.get("response_transform") == "ln(pb)"
            fitted_raw = [float(model["intercept"]) + float(model[f"{current_key}_coefficient"]) * x for x in xs]
            lows = [math.exp(value - residual_half_width) if is_log_pb else value - residual_half_width for value in fitted_raw]
            highs = [math.exp(value + residual_half_width) if is_log_pb else value + residual_half_width for value in fitted_raw]
            data.extend([
                {"type": "scatter", "mode": "lines", "x": xs, "y": lows,
                 "line": {"width": 0}, "hoverinfo": "skip", "showlegend": False},
                {"type": "scatter", "mode": "lines", "x": xs, "y": highs,
                 "fill": "tonexty", "fillcolor": "rgba(217,119,6,.12)",
                 "line": {"width": 0}, "name": "历史残差描述带", "hoverinfo": "skip"},
            ])
            data.append({
                "type": "scatter", "mode": "lines", "x": xs,
                "y": [math.exp(value) if is_log_pb else value for value in fitted_raw],
                "name": "历史经验映射", "line": {"color": "#d97706", "width": 2},
                "hovertemplate": f"{x_label} %{{x:.2f}}<br>拟合PB %{{y:.2f}}<extra></extra>",
            })
            future_points = []
            for forecast in bundle.get("forecast_table") or []:
                value = (forecast.get("internal") or {}).get(current_key)
                if value and value.get("value") is not None:
                    expected_return = float(value["value"])
                    fitted = float(model["intercept"]) + float(model[f"{current_key}_coefficient"]) * expected_return
                    future_points.append({
                        "horizon": forecast.get("horizon"), "return": expected_return,
                        "pb": math.exp(fitted) if is_log_pb else fitted,
                    })
            if future_points:
                data.append({
                    "type": "scatter", "mode": "lines+markers+text",
                    "x": [item["return"] for item in future_points],
                    "y": [item["pb"] for item in future_points],
                    "text": [item["horizon"] for item in future_points], "textposition": "bottom center",
                    "name": "内部预测路径", "line": {"color": "#7c3aed", "dash": "dot"},
                    "marker": {"size": 10, "color": "#7c3aed"},
                    "hovertemplate": f"%{{text}}<br>{x_label} %{{x:.2f}}<br>历史关系对应PB %{{y:.2f}}<extra></extra>",
                })
        figures[key] = ({
            "data": data,
            "layout": {
                "height": 330, "margin": {"l": 55, "r": 18, "t": 18, "b": 52},
                "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "#fbfdff",
                "legend": {"orientation": "h", "x": 0, "y": 1.12},
                "xaxis": {
                    "title": {"text": x_label, "standoff": 12},
                    "gridcolor": "#e8edf5", "showline": True, "linecolor": "#52627b",
                    "linewidth": 1.2, "ticks": "outside", "tickcolor": "#52627b",
                    "automargin": True, "zeroline": True, "zerolinecolor": "#cbd5e1",
                },
                "yaxis": {
                    "title": {"text": "市净率 PB（倍）", "standoff": 10},
                    "gridcolor": "#e8edf5", "showline": True, "linecolor": "#52627b",
                    "linewidth": 1.2, "ticks": "outside", "tickcolor": "#52627b",
                    "automargin": True, "rangemode": "tozero",
                },
            },
        } if data else None)
        models[key] = model
    pb_history = list(asset.get("pb_history") or [])
    band = asset.get("pb_band") or {}
    figures["pb_history"] = ({
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "x": [row.get("as_of_date") for row in pb_history],
                "y": [row.get("value_num") for row in pb_history],
                "name": "月末PB",
                "line": {"color": "#2470b8", "width": 2},
                "hovertemplate": "%{x}<br>PB %{y:.2f}倍<extra></extra>",
            },
            *[
                {
                    "type": "scatter",
                    "mode": "lines",
                    "x": [
                        pb_history[0].get("as_of_date"),
                        pb_history[-1].get("as_of_date"),
                    ],
                    "y": [float(band[field]), float(band[field])],
                    "name": label,
                    "line": {"color": color, "width": 1.5, "dash": dash},
                    "hovertemplate": f"{label} %{{y:.2f}}倍<extra></extra>",
                }
                for field, label, color, dash in (
                    ("q20", "历史20%分位", "#15836d", "dot"),
                    ("median", "历史中位", "#d97706", "dash"),
                    ("q80", "历史80%分位", "#b33d34", "dot"),
                )
                if band.get(field) is not None
            ],
        ],
        "layout": {
            "height": 330,
            "margin": {"l": 55, "r": 18, "t": 18, "b": 52},
            "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "#fbfdff",
            "legend": {"orientation": "h", "x": 0, "y": 1.14},
            "xaxis": {
                "title": "估值时点",
                "type": "date",
                "tickformat": "%Y-%m",
                "nticks": 8,
                "automargin": True,
            },
            "yaxis": {"title": "PB (倍)", "gridcolor": "#e8edf5"},
        },
    } if pb_history else None)

    def price_band_figure(
        band_view: dict[str, Any] | None,
        *,
        multiple_label: str,
    ) -> dict[str, Any] | None:
        rows = list((band_view or {}).get("rows") or [])
        if not rows:
            return None
        x_values = [row["date"] for row in rows]
        return {
            "data": [
                {
                    "type": "scatter", "mode": "lines", "x": x_values,
                    "y": [row["q20_price"] for row in rows],
                    "name": "历史20%分位价格",
                    "line": {"color": "#14856f", "width": 1.5},
                    "hovertemplate": "%{x}<br>20%分位价格 %{y:.2f}元<extra></extra>",
                },
                {
                    "type": "scatter", "mode": "lines", "x": x_values,
                    "y": [row["q80_price"] for row in rows],
                    "name": "20%—80%估值带", "fill": "tonexty",
                    "fillcolor": "rgba(217,119,6,.12)",
                    "line": {"color": "#ba4a3c", "width": 1.5},
                    "hovertemplate": "%{x}<br>80%分位价格 %{y:.2f}元<extra></extra>",
                },
                {
                    "type": "scatter", "mode": "lines", "x": x_values,
                    "y": [row["median_price"] for row in rows],
                    "name": "历史中位价格",
                    "line": {"color": "#d97706", "width": 1.8, "dash": "dash"},
                    "hovertemplate": "%{x}<br>中位价格 %{y:.2f}元<extra></extra>",
                },
                {
                    "type": "scatter", "mode": "lines", "x": x_values,
                    "y": [row["close"] for row in rows],
                    "name": "前复权收盘价",
                    "line": {"color": "#182844", "width": 2.5},
                    "hovertemplate": "%{x}<br>收盘价 %{y:.2f}元<extra></extra>",
                },
            ],
            "layout": {
                "height": 360,
                "margin": {"l": 66, "r": 24, "t": 38, "b": 62},
                "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "#fbfdff",
                "title": {
                    "text": f"{multiple_label} Band（股价与历史估值分位）",
                    "x": 0.01, "xanchor": "left", "font": {"size": 13, "color": "#33415c"},
                },
                "legend": {
                    "orientation": "h", "x": 0, "y": 1.12, "font": {"size": 10},
                },
                "xaxis": {
                    "title": {"text": "交易日期", "standoff": 12},
                    "type": "date", "tickformat": "%Y-%m", "nticks": 8,
                    "showline": True, "linecolor": "#52627b", "linewidth": 1.2,
                    "ticks": "outside", "tickcolor": "#52627b",
                    "gridcolor": "#edf1f6", "automargin": True,
                },
                "yaxis": {
                    "title": {"text": "股价（元/股）", "standoff": 10},
                    "showline": True, "linecolor": "#52627b", "linewidth": 1.2,
                    "ticks": "outside", "tickcolor": "#52627b",
                    "gridcolor": "#e5eaf1", "automargin": True,
                    "rangemode": "tozero", "zeroline": True,
                    "zerolinecolor": "#cbd5e1",
                },
                "hovermode": "x unified",
            },
        }

    figures["pb_price_band"] = price_band_figure(
        asset.get("pb_price_band"), multiple_label="PB"
    )
    figures["pe_price_band"] = price_band_figure(
        asset.get("pe_price_band"), multiple_label="PE"
    )

    actual_roe = list(asset.get("roe_history") or [])
    forecast_table = list(bundle.get("forecast_table") or [])
    roe_traces: list[dict[str, Any]] = []
    if actual_roe:
        roe_traces.append({
            "type": "scatter", "mode": "lines+markers",
            "x": [str(row.get("fiscal_year")) for row in actual_roe],
            "y": [row.get("value_num") for row in actual_roe],
            "name": "历史实际ROE", "line": {"color": "#2470b8", "width": 2},
            "hovertemplate": "%{x}<br>实际ROE %{y:.2f}%<extra></extra>",
        })
    for side, label, color, dash in (
        ("internal", "内部预测ROE", "#7c3aed", "solid"),
        ("consensus", "Wind一致预期ROE", "#d97706", "dash"),
    ):
        points = [
            (
                str(
                    (forecast.get(side) or {}).get("roe", {}).get(
                        "fiscal_year",
                        "",
                    )
                    or (2025 + index)
                ),
                (forecast.get(side) or {}).get("roe", {}).get("value"),
            )
            for index, forecast in enumerate(forecast_table, start=1)
            if (forecast.get(side) or {}).get("roe", {}).get("value") is not None
        ]
        if points:
            roe_traces.append({
                "type": "scatter", "mode": "lines+markers",
                "x": [point[0] for point in points],
                "y": [point[1] for point in points],
                "name": label, "line": {"color": color, "width": 2, "dash": dash},
                "hovertemplate": f"%{{x}}<br>{label} %{{y:.2f}}%<extra></extra>",
            })
    figures["roe_path"] = ({
        "data": roe_traces,
        "layout": {
            "height": 330,
            "margin": {"l": 55, "r": 18, "t": 18, "b": 52},
            "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "#fbfdff",
            "legend": {"orientation": "h", "x": 0, "y": 1.14},
            "xaxis": {
                "title": {"text": "报告年度 / 预测年度", "standoff": 12},
                "type": "category",
                "automargin": True,
                "showline": True, "linecolor": "#52627b", "linewidth": 1.2,
                "ticks": "outside", "tickcolor": "#52627b",
            },
            "yaxis": {
                "title": {"text": "净资产收益率 ROE（%）", "standoff": 10},
                "gridcolor": "#e8edf5", "showline": True,
                "linecolor": "#52627b", "linewidth": 1.2,
                "ticks": "outside", "tickcolor": "#52627b",
                "automargin": True, "zeroline": True, "zerolinecolor": "#cbd5e1",
            },
        },
    } if roe_traces else None)
    return {
        **figures,
        "pb_roe_model": models["pb_roe"],
        "pb_roa_model": models["pb_roa"],
        "pb_price_band_availability": asset.get("pb_price_band_availability"),
        "pe_price_band_availability": asset.get("pe_price_band_availability"),
    }


def _company_search_rows(q: str = "", market: str = "", *, limit: int = 300) -> list[dict[str, Any]]:
    clauses = ["1=1"]
    params: list[Any] = []
    if q:
        token = f"%{q.strip()}%"
        alias_sql = (
            " OR EXISTS(SELECT 1 FROM company_identity_alias a "
            "WHERE a.canonical_company_id=c.id AND a.alias LIKE ?)"
            if _table_exists("company_identity_alias") else ""
        )
        clauses.append(f"(c.name LIKE ? OR c.ticker LIKE ?{alias_sql})")
        params.extend([token, token] + ([token] if alias_sql else []))
    if market:
        clauses.append("c.market=?")
        params.append(market)
    params.append(max(1, min(int(limit), 500)))
    return query_all(
        f"""SELECT c.id,c.name,c.ticker,c.market,c.listing_status,
                    COALESCE(
                      NULLIF(trim(c.brief_intro),''),
                      (
                        SELECT COALESCE(
                                 NULLIF(trim(cp2.brief_intro),''),
                                 NULLIF(trim(cp2.summary),''),
                                 NULLIF(trim(cp2.main_products),'')
                               )
                          FROM company_profile cp2
                         WHERE cp2.company_id=c.id
                           AND COALESCE(
                                 NULLIF(trim(cp2.brief_intro),''),
                                 NULLIF(trim(cp2.summary),''),
                                 NULLIF(trim(cp2.main_products),'')
                               ) IS NOT NULL
                         ORDER BY cp2.id DESC
                         LIMIT 1
                      )
                    ) AS brief_intro,
                    c.market_cap_cny,c.pe_ttm,c.pb,c.roe,c.roa,
                    c.valuation_as_of,c.financial_metrics_as_of,
                    max(cp.last_updated) AS last_researched_at,
                   group_concat(DISTINCT i.name) AS industries
              FROM company c
              LEFT JOIN company_profile cp ON cp.company_id=c.id
              LEFT JOIN company_industry ci ON ci.company_id=c.id
              LEFT JOIN industry i ON i.id=ci.industry_id
             WHERE {' AND '.join(clauses)}
             GROUP BY c.id
             ORDER BY (c.ticker IS NULL OR trim(c.ticker)=''),
                      last_researched_at IS NULL,last_researched_at DESC,c.name
             LIMIT ?""",
        tuple(params),
    )


def _prepare_company_index_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Overlay the company directory with the live read-only financial view.

    ``research.db.company`` keeps nullable legacy aggregates for compatibility;
    the company directory must not treat those columns as the current source.
    The same financial observations used by company detail pages are applied
    here in memory, with a plain-language state for loss-making or unavailable
    PE instead of an unexplained dash.
    """
    if not rows:
        return rows
    company_ids = [int(row["id"]) for row in rows]
    try:
        bundles = financial_company_current_metrics_batch(
            company_ids, db_path=FINANCIAL_DB_PATH,
        )
    except Exception:
        log.exception("公司索引批量读取 financial.db 失败")
        bundles = {}

    for row in rows:
        # 旧公司简介可能把抽取方法写进了公开描述；目录只展示自然中文，
        # 生产层方法名仍保留在来源/审计记录中。
        intro = str(row.get("brief_intro") or "")
        intro = re.sub(
            r"\bweb_fetch\b(?:\s*[（(]未审计[）)])?",
            "公开资料待补充",
            intro,
        )
        intro = re.sub(r"\bpdf_direct\b", "研报原文", intro)
        intro = re.sub(r"\binferred\b", "研究推断", intro)
        row["brief_intro"] = intro

        company_id = int(row["id"])
        bundle = bundles.get(company_id) or {}
        security = bundle.get("security") or {}
        row_ticker = str(row.get("ticker") or "").strip().upper()
        financial_ticker = str(security.get("ticker") or "").strip().upper()
        current = (
            bundle.get("current_metrics") or {}
            if not (
                row_ticker and financial_ticker
                and row_ticker != financial_ticker
            )
            else {}
        )
        providers: list[str] = []
        as_of_dates: list[str] = []
        for key in ("pe_ttm", "pb", "roe", "roa", "eps_ttm"):
            observation = current.get(key) or {}
            if observation.get("value_num") is not None:
                # 公司索引与详情页都以 financial.db 为当前事实源；旧聚合值
                # 只在没有规范财务链接时兼容展示。
                row[key] = observation["value_num"]
            provider = str(observation.get("provider_label") or "").strip()
            if provider and provider not in providers:
                providers.append(provider)
            as_of = str(observation.get("as_of_date") or "").strip()
            if as_of:
                as_of_dates.append(as_of)

        is_unlisted = (
            row.get("listing_status") in UNLISTED_LISTING_STATUSES
            or not row.get("ticker")
        )
        pe = row.get("pe_ttm")
        eps = row.get("eps_ttm")
        if _positive_pe(pe):
            pe_display = f"{float(pe):.2f}×"
        else:
            try:
                loss_making = (
                    (pe is not None and float(pe) <= 0)
                    or (eps is not None and float(eps) <= 0)
                )
            except (TypeError, ValueError):
                loss_making = False
            pe_display = (
                "亏损/不适用"
                if loss_making
                else "不适用" if is_unlisted
                else "暂缺"
            )

        metric_displays: dict[str, str] = {"pe_ttm": pe_display}
        for key, suffix in (("pb", "×"), ("roe", "%"), ("roa", "%")):
            value = row.get(key)
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = math.nan
            metric_displays[key] = (
                f"{number:.2f}{suffix}"
                if math.isfinite(number)
                else "不适用" if is_unlisted
                else "暂缺"
            )
        row["metric_displays"] = metric_displays
        row["financial_provider_label"] = " / ".join(providers)
        row["financial_snapshot_as_of"] = (
            max(as_of_dates)
            if as_of_dates
            else row.get("financial_metrics_as_of")
            or row.get("valuation_as_of")
        )
    return rows


def _company_opportunity_links(company_id: int, ticker: str | None) -> list[dict[str, Any]]:
    """Read-only cross-link; Opportunity Lens remains a separate database."""
    from tools.opportunity_lens.db import connect as opportunity_connect

    try:
        conn = opportunity_connect(OPPORTUNITY_DB_PATH, readonly=True)
    except (FileNotFoundError, sqlite3.OperationalError):
        return []
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='opportunity_entity_investment_target'"
        ).fetchone()
        if not exists:
            return []
        params: list[Any] = [int(company_id)]
        ticker_clause = ""
        if str(ticker or "").strip():
            ticker_clause = " OR upper(t.ticker)=upper(?)"
            params.append(str(ticker).strip())
        rows = conn.execute(
            f"""SELECT DISTINCT r.id AS run_id,
                       COALESCE(NULLIF(r.display_title,''),NULLIF(r.question,''),r.research_question) AS title,
                       r.run_readiness_status,r.updated_at,t.id AS target_id,
                       COALESCE(e.display_name,e.canonical_name) AS entity_name
                  FROM opportunity_entity_investment_target t
                  JOIN opportunity_run r ON r.id=t.run_id
                  JOIN opportunity_entity e ON e.id=t.entity_id
                 WHERE t.company_id=?{ticker_clause}
                 ORDER BY r.updated_at DESC,r.id DESC LIMIT 30""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.route("/companies")
def companies_index():
    q = str(request.args.get("q") or "").strip()
    market = str(request.args.get("market") or "").strip()
    companies = _prepare_company_index_rows(_company_search_rows(q, market))
    markets = [row["market"] for row in query_all(
        "SELECT DISTINCT market FROM company WHERE market IS NOT NULL AND trim(market)<>'' ORDER BY market"
    )]
    recent = _company_search_rows(limit=12)
    return render_template(
        "companies.html", companies=companies, markets=markets, q=q, market=market, recent=recent,
    )


@app.route("/api/companies/search")
def companies_search_api():
    q = str(request.args.get("q") or "").strip()
    rows = _company_search_rows(q, limit=30)
    return jsonify({
        "query": q,
        "results": [{
            "id": row["id"], "name": row["name"], "ticker": row.get("ticker"),
            "market": row.get("market"), "url": url_for("company_tag", company_id=row["id"]),
        } for row in rows],
    })


_PEER_PRODUCT_LAYER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # 顺序代表产品形态的优先级。比如“光模块并自研光芯片”仍以对外销售的
    # 模块/整机为主层级，不能因为垂直整合而被归入纯芯片公司。
    # PCB 公司常同时披露 GPU、光模块等下游应用，必须先按自身出售的
    # PCB/HDI 产品归类，否则会被误分到芯片或整机层。
    ("PCB/HDI制造", (
        "hdi", "hlc", "pcb", "多层板", "高频高速板", "封装基板",
        "载板", "线路板", "fpc", "slp", "rigid-flex",
    )),
    # 电池公司常同时披露正极材料、回收或整车业务。先按对外提供的
    # 电芯/电池系统归类，避免被后面的“材料”规则拆散，导致同一行业
    # 的 PB—ROE / PB—ROA 同行截面无法形成。
    ("锂电池/电池系统", (
        "动力电池", "储能电池", "电池系统", "刀片电池", "电芯",
        "锂离子电池", "消费电池",
    )),
    ("整机/模块", ("光模块", "收发模块", "整机模块", "整机系统", "整机")),
    ("芯片/晶圆", ("芯片", "晶圆", "硅片", "衬底", "asic", "gpu")),
    ("制造设备/仪器", ("设备", "仪器", "装备", "产线", "测试机", "检测机")),
    ("器件/零部件", ("器件", "光引擎", "组件", "元件", "零部件", "激光器")),
    ("材料", ("材料", "化学品", "铜箔", "玻纤", "树脂")),
    ("软件/平台/服务", ("软件", "平台", "云服务", "运营服务", "订阅")),
)


def _peer_product_layer(value: Any) -> str | None:
    """从已披露主营产品中做保守的产业层级归类。

    这里只决定哪些公司可以进入“待比较样本”，不替代研究员的正式可比
    公司选择。没有可解释产品文本时返回 None，避免把整条产业链当同行。
    """
    text = str(value or "").strip().lower()
    if not text:
        return None
    for label, keywords in _PEER_PRODUCT_LAYER_RULES:
        if any(keyword in text for keyword in keywords):
            return label
    return None


def _asset_return_peer_candidates(
    company_id: int,
    industry_id: int | None,
    profile: dict[str, Any] | None,
) -> tuple[list[int], str]:
    """生成资产回报诊断的保守同行候选及人话筛选说明。"""
    if not industry_id:
        return [], "尚未识别公司的核心行业，因此不生成同行资产回报样本。"
    current_products = (profile or {}).get("main_products") or (profile or {}).get("brief_intro")
    layer = _peer_product_layer(current_products)
    if not layer:
        return [], "现有主营产品资料不足以识别可比产品层级，因此不把同一产业链公司机械视为同行。"
    rows = query_all(
        """
        WITH latest_profile AS (
          SELECT cp.* FROM company_profile cp
          JOIN (
            SELECT company_id, industry_id, MAX(id) AS max_id
            FROM company_profile GROUP BY company_id, industry_id
          ) x ON x.max_id=cp.id
        )
        SELECT ci.company_id, c.ticker, c.listing_status,
               cp.main_products,
               COALESCE(NULLIF(cp.brief_intro,''), NULLIF(c.brief_intro,'')) AS business_text
        FROM company_industry ci
        JOIN company c ON c.id=ci.company_id
        LEFT JOIN latest_profile cp
          ON cp.company_id=ci.company_id AND cp.industry_id=ci.industry_id
        WHERE ci.industry_id=?
          AND c.ticker IS NOT NULL AND trim(c.ticker)<>''
        ORDER BY ci.company_id
        """,
        (industry_id,),
    )
    ids: list[int] = []
    for row in rows:
        product_text = row.get("main_products") or row.get("business_text")
        if _peer_product_layer(product_text) == layer:
            ids.append(int(row["company_id"]))
    if company_id not in ids:
        ids.append(company_id)
    return ids[:40], (
        f"候选样本先限定为同一核心行业、已上市且产品层级同为“{layer}”的公司，"
        "再仅展示独立财务库中有 PB 或资产回报数据的公司。不同市场的会计口径、"
        "增长和风险仍需人工复核，因此该截面只用于诊断，不直接套用行业平均倍数。"
    )


def _asset_return_peer_summary(
    rows: list[dict[str, Any]], company_id: int,
) -> dict[str, Any] | None:
    """Summarize a comparable cross-section without turning its median into fair value."""
    current = next(
        (row for row in rows if row.get("research_company_id") == company_id),
        None,
    )
    if not current:
        return None
    same_market = [
        row for row in rows
        if row.get("research_company_id") != company_id
        and row.get("market") == current.get("market")
    ]
    peers = same_market if len(same_market) >= 2 else [
        row for row in rows if row.get("research_company_id") != company_id
    ]
    if len(peers) < 2:
        return None

    def value(row: dict[str, Any], metric: str) -> float | None:
        payload = row.get(metric)
        if not isinstance(payload, dict) or payload.get("value_num") is None:
            return None
        try:
            result = float(payload["value_num"])
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    medians: dict[str, float | None] = {}
    sample_sizes: dict[str, int] = {}
    for metric in ("pb", "roe", "roa"):
        values = [
            candidate for row in peers
            if (candidate := value(row, metric)) is not None
        ]
        medians[metric] = median(values) if len(values) >= 2 else None
        sample_sizes[metric] = len(values)
    current_values = {
        metric: value(current, metric) for metric in ("pb", "roe", "roa")
    }
    if medians["pb"] is None and medians["roe"] is None:
        return None

    parts: list[str] = []
    labels = {"pb": "PB", "roe": "ROE", "roa": "ROA"}
    suffix = {"pb": "倍", "roe": "%", "roa": "%"}
    for metric in ("pb", "roe", "roa"):
        current_value = current_values[metric]
        peer_median = medians[metric]
        if current_value is not None and peer_median is not None:
            parts.append(
                f"本公司{labels[metric]}为{current_value:.2f}{suffix[metric]}，"
                f"同行中位数为{peer_median:.2f}{suffix[metric]}"
            )
    pb = current_values["pb"]
    pb_median = medians["pb"]
    roe = current_values["roe"]
    roe_median = medians["roe"]
    if None not in (pb, pb_median, roe, roe_median):
        assert pb is not None and pb_median is not None
        assert roe is not None and roe_median is not None
        if pb > pb_median * 1.2 and roe <= roe_median * 1.1:
            interpretation = (
                "估值溢价明显高于资产回报优势，后续需要更强的增长、利润率和现金流兑现。"
            )
        elif pb > pb_median * 1.2 and roe > roe_median * 1.1:
            interpretation = (
                "估值和资产回报都高于同行，但高PB能否持续仍取决于超额ROE的持续时间。"
            )
        elif pb < pb_median * 0.8 and roe >= roe_median:
            interpretation = (
                "资产回报不弱而估值低于同行，值得继续检查增长持续性、周期位置和个别风险。"
            )
        else:
            interpretation = (
                "估值与资产回报大致处于同一同行区间，差异仍需结合增长、业务结构和杠杆解释。"
            )
    else:
        interpretation = "可用指标尚不完整，本截面只展示现有数据，不据此给出合理倍数。"
    return {
        "peer_count": len(peers),
        "scope": "同市场同行" if peers is same_market else "跨市场同行",
        "current": current_values,
        "medians": medians,
        "sample_sizes": sample_sizes,
        "text": "；".join(parts) + "。" + interpretation,
    }


@app.route("/tools")
def tools_index():
    """Read-only landing page for researcher calculators."""
    return render_template("tools_index.html")


def valuation_tracker_repository() -> ValuationTrackerRepository:
    if VALUATION_TRACKER_REPOSITORY is None:
        raise RuntimeError("市值空间与估值跟踪仅在 PostgreSQL 正式数据层可用")
    return VALUATION_TRACKER_REPOSITORY


@app.route("/tools/valuation-tracker")
def valuation_tracker_page():
    """Render the whole watchlist from one set-based PostgreSQL read."""
    try:
        members = valuation_tracker_repository().watchlist()
    except Exception as exc:
        log.exception("加载市值空间与估值跟踪失败")
        return render_template(
            "valuation_tracker.html", members=[], tracker_error=str(exc)
        ), 503
    return render_template(
        "valuation_tracker.html", members=members, tracker_error=None
    )


@app.route(
    "/api/valuation-tracker/member/<int:member_id>/valuation", methods=["POST"]
)
def valuation_tracker_edit_valuation(member_id: int):
    try:
        principal = require_user_content_principal(
            app, request, permission="valuation_tracker:publish", csrf=True
        )
        payload = request.get_json(silent=True) or {}
        kind = str(payload.pop("kind", ""))
        expected_revision = int(payload.pop("expected_revision"))
        idempotency_key = str(
            request.headers.get("X-Idempotency-Key") or ""
        ).strip()
        if not idempotency_key:
            return jsonify({
                "ok": False, "code": "idempotency_required",
                "error": "缺少 X-Idempotency-Key",
            }), 400
        result = valuation_tracker_repository().edit_valuation(
            member_id, kind, payload, expected_revision=expected_revision,
            actor=principal.subject, idempotency_key=idempotency_key,
        )
        return jsonify({"ok": True, "result": result})
    except (ValueError, TypeError) as exc:
        return jsonify({
            "ok": False, "code": "invalid_payload", "error": str(exc)
        }), 400
    except Exception as exc:
        return _user_content_error(exc)


@app.route(
    "/api/valuation-tracker/member/<int:member_id>/policy", methods=["POST"]
)
def valuation_tracker_edit_policy(member_id: int):
    try:
        principal = require_user_content_principal(
            app, request, permission="valuation_tracker:write", csrf=True
        )
        payload = request.get_json(silent=True) or {}
        idempotency_key = str(
            request.headers.get("X-Idempotency-Key") or ""
        ).strip()
        if not idempotency_key:
            return jsonify({
                "ok": False, "code": "idempotency_required",
                "error": "缺少 X-Idempotency-Key",
            }), 400
        result = valuation_tracker_repository().edit_policy(
            member_id,
            float(payload["researcher_threshold"]),
            float(payload["ai_threshold"]),
            int(payload.get("max_age_hours", 48)),
            str(payload.get("reason") or ""),
            expected_revision=int(payload["expected_policy_revision"]),
            actor=principal.subject,
            idempotency_key=idempotency_key,
        )
        return jsonify({"ok": True, "result": result})
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({
            "ok": False, "code": "invalid_payload", "error": str(exc)
        }), 400
    except Exception as exc:
        return _user_content_error(exc)


def _load_battery_calculator_model() -> dict[str, Any]:
    model_path = (
        ROOT
        / "config"
        / "battery_calculator_models"
        / "battery_calculator_model_v1.json"
    )
    if not model_path.exists():
        abort(404)
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("读取锂电池行业计算器冻结模型失败")
        abort(500)
    if model.get("schemaVersion") != "battery_calculator.model.v1":
        log.error("锂电池行业计算器模型版本不兼容: %s", model.get("schemaVersion"))
        abort(500)
    return model


@app.route("/tools/battery-calculator")
def battery_calculator():
    """Browser-only lithium-battery operating and valuation workbench."""
    model = _load_battery_calculator_model()
    companies = model.get("companies") or []
    selected_company_id = request.args.get("company_id", type=int)
    selected_key = str(
        selected_company_id
        if selected_company_id is not None
        else (companies[0] if companies else {}).get("companyId", "")
    )
    return render_template(
        "battery_calculator.html",
        battery_model_json=json.dumps(model, ensure_ascii=False),
        selected_company_key=selected_key,
        model_as_of=model.get("asOfDate"),
        model_sha256=model.get("contentSha256"),
    )


@app.route("/industry/lithium-battery/comparison")
def battery_industry_comparison():
    """Cross-company battery operating, return and valuation comparison."""
    model = _load_battery_calculator_model()
    return render_template(
        "battery_industry_comparison.html",
        battery_model_json=json.dumps(model, ensure_ascii=False),
        model_as_of=model.get("asOfDate"),
        model_sha256=model.get("contentSha256"),
    )


@app.route("/tools/copper-calculator")
def copper_calculator():
    return _render_copper_calculator(comparison_mode=False)


@app.route("/industry/copper/comparison")
def copper_industry_comparison():
    return _render_copper_calculator(comparison_mode=True)


def _render_copper_calculator(*, comparison_mode: bool):
    """Editable browser-only copper project, cash-flow and valuation model."""
    model_path = (
        ROOT
        / "config"
        / "copper_calculator_models"
        / "copper_calculator_model_v1.json"
    )
    if not model_path.exists():
        abort(404)
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("读取铜行业计算器冻结模型失败")
        abort(500)
    if model.get("schemaVersion") != "copper_calculator.model.v1":
        log.error("铜行业计算器模型版本不兼容: %s", model.get("schemaVersion"))
        abort(500)
    companies = model.get("companies") or []
    selected_company_id = request.args.get("company_id", type=int)
    selected_key = str(
        selected_company_id
        if selected_company_id is not None
        else (companies[0] if companies else {}).get("companyId", "")
    )
    return render_template(
        "copper_calculator.html",
        copper_model_json=json.dumps(model, ensure_ascii=False),
        selected_company_key=selected_key,
        model_as_of=model.get("asOfDate"),
        model_sha256=model.get("contentSha256"),
        comparison_mode=comparison_mode,
    )


@app.route("/tools/lithium-calculator")
def lithium_calculator():
    return _render_lithium_calculator(comparison_mode=False)


@app.route("/industry/lithium/comparison")
def lithium_industry_comparison():
    return _render_lithium_calculator(comparison_mode=True)


def _render_lithium_calculator(*, comparison_mode: bool):
    """Interactive lithium-carbonate project and valuation calculator.

    The calculator is read-only with respect to all project databases. Researcher
    scenarios are stored in browser localStorage by the template, so editing a
    scenario cannot overwrite the frozen AI model or supplier observations.  The
    deployable project ledger is compiled from the reference workbook and keeps
    each mine/salar, its stated ownership, 2025-2030 volume, cost and notes.  It
    must not be collapsed back into one company-level resource row.
    """
    calculator_inputs = resolve_lithium_inputs(
        RUNTIME_LAYOUT.code_root,
        state_root=RUNTIME_LAYOUT.state_root,
    )
    model_path = calculator_inputs.independent_model
    recon_path = calculator_inputs.reconciliation
    project_ledger_path = calculator_inputs.project_ledger
    if calculator_inputs.missing():
        abort(404)
    if calculator_inputs.used_legacy_cache:
        log.warning(
            "碳酸锂计算器正在使用旧 cache 冻结模型；"
            "请同步 config/lithium_calculator_models"
        )
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        recon = json.loads(recon_path.read_text(encoding="utf-8"))
        project_ledger = json.loads(
            project_ledger_path.read_text(encoding="utf-8")
        )
    except Exception:
        log.exception("读取锂行业计算器冻结模型失败")
        abort(500)
    years = [
        int(year)
        for year in (project_ledger.get("years") or range(2025, 2031))
    ]
    workbook_by_name = {
        str(row.get("name")): row
        for row in (project_ledger.get("companies") or [])
    }
    recon_by_ticker = {
        str(row.get("ticker")): row for row in recon.get("companies") or []
    }
    companies: list[dict[str, Any]] = []
    company_names: set[str] = set()
    # 参考模型汇总页中的2024资源基数。2025年以后统一由逐项目记录
    # 动态汇总，新增项目会自动进入比较表；2024只作为不可变历史参考。
    sheet1_resource_baseline_2024 = {
        "002460.SZ": {"attributable": 5.0241333333, "gross": 17.5713833333},
        "002466.SZ": {"attributable": 9.0221875, "gross": 38.14},
        "002756.SZ": {"attributable": 2.049253055, "gross": 3.10},
        "002738.SZ": {"attributable": 4.0, "gross": 4.0},
        "000408.SZ": {"attributable": 1.20, "gross": 1.20},
        "000792.SZ": {"attributable": 2.7068, "gross": 5.30},
        "002192.SZ": {"attributable": 1.0, "gross": None},
        "002497.SZ": {"attributable": 0.6496434783, "gross": 1.4279891304},
        "002240.SZ": {"attributable": 3.375, "gross": 3.75},
        "000688.SZ": {"attributable": 1.0, "gross": 1.0},
        "001203.SZ": {"attributable": 0.0, "gross": 0.0},
        "300390.SZ": {"attributable": 0.04014, "gross": 0.16},
    }

    def annual(
        mapping: dict[str, Any], year: int, default: float = 0.0
    ) -> float:
        return float(mapping.get(str(year), mapping.get(year, default)) or 0.0)

    def series(
        mapping: dict[str, Any],
        *,
        default: float = 0.0,
        carry_forward: bool = True,
    ) -> dict[str, float]:
        output: dict[str, float] = {}
        last = default
        for year in years:
            value = annual(mapping, year, last if carry_forward else default)
            output[str(year)] = value
            last = value
        return output

    def project_from_workbook(row: dict[str, Any]) -> dict[str, Any]:
        mismatch = bool(row.get("ownershipReferenceMismatch"))
        note = " ".join(
            str(row.get("note") or "").replace("\xa0", " ").split()
        )
        volumes = row.get("grossVolumeByYear") or {}
        positive_years = [
            year for year in years
            if float(volumes.get(str(year), 0.0) or 0.0) > 0
        ]
        model_equity_start_year = row.get("modelEquityStartYear")
        if model_equity_start_year is None and positive_years:
            model_equity_start_year = min(positive_years)
        if positive_years and min(positive_years) <= 2025:
            project_status = (
                f"{int(model_equity_start_year)}年起计入模型；在产或爬坡"
            )
        elif positive_years:
            project_status = (
                f"{int(model_equity_start_year)}年起计入模型；规划或建设"
            )
        else:
            project_status = "暂未计入模型；尚未设置产量"
        if mismatch:
            correction = (
                "网页按本项目自身声明权益重算；参考模型底稿中的权益公式曾引用其他项目"
                "的权益单元格，未沿用该错引。"
            )
            note = f"{note}；{correction}" if note else correction
        return {
            "name": row.get("name"),
            "type": "resource",
            "enabled": bool(row.get("enabled", True)),
            "status": project_status,
            "modelEquityStartYear": model_equity_start_year,
            "origin": row.get("origin") or "逐项目研究底稿",
            "note": note,
            "ownershipPct": float(row.get("ownershipPct") or 0.0),
            "profitAttributionPct": float(
                row.get(
                    "profitAttributionPct",
                    row.get("ownershipPct") or 0.0,
                )
                or 0.0
            ),
            "profitAttributionBasis": row.get(
                "profitAttributionBasis"
            ) or "权益产量",
            "profitAttributionFollowsOwnership": bool(
                row.get("profitAttributionFollowsOwnership", True)
            ),
            "volumeByYear": {
                str(year): float(
                    (row.get("grossVolumeByYear") or {}).get(str(year), 0.0)
                    or 0.0
                )
                for year in years
            },
            "costByYear": {
                str(year): float(
                    (row.get("costByYear") or {}).get(str(year), 0.0)
                    or 0.0
                )
                for year in years
            },
            "processingMarginByYear": {
                str(year): 0.0 for year in years
            },
            "fixedProfitByYear": {str(year): 0.0 for year in years},
            "workbookOwnershipExpression": row.get(
                "workbookOwnershipExpression"
            ),
            "ownershipReferenceCorrected": mismatch,
        }

    def project_template_compat(project: dict[str, Any]) -> dict[str, Any]:
        """Keep the live v1 template usable while the v2 tool UI is deferred."""
        volumes = project.get("volumeByYear") or {}
        costs = project.get("costByYear") or {}
        margins = project.get("processingMarginByYear") or {}
        fixed = project.get("fixedProfitByYear") or {}
        project.update(
            {
                "volume2025": annual(volumes, 2025),
                "volume2026": annual(volumes, 2026),
                "volumeTerminal": annual(volumes, 2030),
                "cost": annual(costs, 2030),
                "processingMargin": annual(margins, 2030),
                "fixedProfit2025": annual(fixed, 2025),
                "fixedProfit2026": annual(fixed, 2026),
                "fixedProfitTerminal": annual(fixed, 2030),
            }
        )
        return project

    def aggregate_projects(
        company: dict[str, Any], workbook_company: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        assumptions = company.get("assumptions") or {}
        volumes = assumptions.get("product_volume") or {}
        shares = assumptions.get("resource_share") or {}
        costs = assumptions.get("resource_cost") or {}
        margins = assumptions.get("processing_margin") or {}
        other_profit = assumptions.get("other_profit") or {}
        corporate_cost = assumptions.get("corporate_cost") or {}
        projects = (
            [
                project_from_workbook(row)
                for row in (workbook_company.get("projects") or [])
            ]
            if workbook_company else []
        )
        if not projects:
            resource_volume = {
                str(year): annual(volumes, year)
                * annual(shares, year)
                for year in years
            }
            projects.append(
                {
                    "name": "自有及权益资源组合（待拆项目）",
                    "type": "resource",
                    "enabled": True,
                    "status": "公司级回退，待拆项目",
                    "origin": "冻结研究模型；参考模型未提供该公司项目页",
                    "note": (
                        "这是公司级回退值。新增或核实矿山后可在明细模式"
                        "继续拆分，不会覆盖冻结模型。"
                    ),
                    "ownershipPct": 100.0,
                    "profitAttributionPct": 100.0,
                    "profitAttributionBasis": "权益产量",
                    "profitAttributionFollowsOwnership": True,
                    "volumeByYear": resource_volume,
                    "costByYear": series(costs),
                    "processingMarginByYear": {
                        str(year): 0.0 for year in years
                    },
                    "fixedProfitByYear": {
                        str(year): 0.0 for year in years
                    },
                }
            )
        processing_volume = {
            str(year): annual(volumes, year)
            * max(0.0, 1.0 - annual(shares, year))
            for year in years
        }
        projects.extend(
            [
                {
                    "name": "外购原料锂盐加工组合",
                    "type": "processing",
                    "enabled": True,
                    "status": "经营模型聚合项",
                    "origin": "冻结独立研究模型",
                    "note": "仅计算外购原料加工利润，不重复计入自有资源量。",
                    "ownershipPct": 100.0,
                    "profitAttributionPct": 100.0,
                    "profitAttributionFollowsOwnership": True,
                    "volumeByYear": processing_volume,
                    "costByYear": {
                        str(year): 0.0 for year in years
                    },
                    "processingMarginByYear": series(margins),
                    "fixedProfitByYear": {
                        str(year): 0.0 for year in years
                    },
                },
                {
                    "name": "其他业务及权益法收益",
                    "type": "other",
                    "enabled": True,
                    "status": "经营模型聚合项",
                    "origin": "冻结独立研究模型",
                    "note": "按公司其他业务和权益法收益的独立估算计入。",
                    "ownershipPct": 100.0,
                    "profitAttributionPct": 100.0,
                    "profitAttributionFollowsOwnership": True,
                    "volumeByYear": {
                        str(year): 0.0 for year in years
                    },
                    "costByYear": {
                        str(year): 0.0 for year in years
                    },
                    "processingMarginByYear": {
                        str(year): 0.0 for year in years
                    },
                    "fixedProfitByYear": {
                        str(year): annual(other_profit, year) * 10.0
                        for year in years
                    },
                },
                {
                    "name": "公司层费用与少数股东影响",
                    "type": "other",
                    "enabled": True,
                    "status": "经营模型聚合项",
                    "origin": "冻结独立研究模型",
                    "note": (
                        "以负利润计入，承接公司层费用、利息和少数股东"
                        "等无法归入单矿的影响。"
                    ),
                    "ownershipPct": 100.0,
                    "profitAttributionPct": 100.0,
                    "profitAttributionFollowsOwnership": True,
                    "volumeByYear": {
                        str(year): 0.0 for year in years
                    },
                    "costByYear": {
                        str(year): 0.0 for year in years
                    },
                    "processingMarginByYear": {
                        str(year): 0.0 for year in years
                    },
                    "fixedProfitByYear": {
                        str(year): -annual(corporate_cost, year) * 10.0
                        for year in years
                    },
                },
            ]
        )
        return [project_template_compat(row) for row in projects]

    def project_bridge(
        projects: list[dict[str, Any]],
        year: int,
        *,
        price: float,
        income_tax_rate: float,
    ) -> dict[str, float]:
        """Recompute the project-level revenue proxy and attributable profit.

        The revenue result is deliberately a bridge rather than an accounting
        forecast: equity-accounted mines and processing operations do not always
        consolidate gross revenue.  The browser uses only the *change* versus
        the frozen project set to update the company financial baseline.
        """
        resource_pre_tax_profit = 0.0
        processing_pre_tax_profit = 0.0
        other_profit = 0.0
        revenue_proxy = 0.0
        incremental_capex = 0.0
        for project in projects:
            if not project.get("enabled", True):
                continue
            ownership = float(project.get("ownershipPct") or 0.0) / 100.0
            project_type = str(project.get("type") or "resource")
            volume = annual(project.get("volumeByYear") or {}, year) * ownership
            incremental_capex += annual(
                project.get("incrementalCapexByYear") or {}, year
            )
            if project_type == "resource":
                cost = annual(project.get("costByYear") or {}, year)
                revenue_proxy += volume * price / 1.13
                gross_volume = annual(
                    project.get("volumeByYear") or {}, year
                )
                profit_attribution = float(
                    project.get(
                        "profitAttributionPct",
                        project.get("ownershipPct") or 0.0,
                    )
                    or 0.0
                ) / 100.0
                profit_volume = gross_volume * profit_attribution
                resource_pre_tax_profit += (
                    profit_volume * (price / 1.13 - cost / 1.13)
                )
            elif project_type == "processing":
                margin = annual(
                    project.get("processingMarginByYear") or {}, year
                )
                revenue_proxy += volume * price / 1.13
                processing_pre_tax_profit += volume * margin / 1.13
            else:
                other_profit += annual(
                    project.get("fixedProfitByYear") or {}, year
                ) * ownership
        after_income_tax = 1.0 - min(
            max(float(income_tax_rate), 0.0), 1.0
        )
        resource_profit = resource_pre_tax_profit * after_income_tax
        processing_profit = processing_pre_tax_profit * after_income_tax
        return {
            "revenue": revenue_proxy,
            "netIncome": resource_profit + processing_profit + other_profit,
            "resourcePreTaxProfit": resource_pre_tax_profit,
            "processingPreTaxProfit": processing_pre_tax_profit,
            "incrementalCapex": incremental_capex,
        }

    def build_financial_bridge(
        company: dict[str, Any],
        base_rows: dict[int, dict[str, Any]],
        projects: list[dict[str, Any]],
        *,
        income_tax_rate: float,
    ) -> dict[str, dict[str, float | None]]:
        """Create editable baselines without presenting inferred OCF as facts."""
        actual = company.get("actual_2025") or {}
        financials: dict[str, dict[str, float | None]] = {
            "2025": {
                "revenue": float(actual.get("revenue_rmb_bn") or 0.0) * 10.0,
                "netIncome": float(actual.get("net_income_rmb_bn") or 0.0) * 10.0,
                "ocf": float(actual.get("operating_cash_flow_rmb_bn") or 0.0)
                * 10.0,
                "capex": float(actual.get("capex_rmb_bn") or 0.0) * 10.0,
                "equity": (
                    float(actual["equity_rmb_bn"]) * 10.0
                    if actual.get("equity_rmb_bn") is not None
                    else None
                ),
                "buyback": 0.0,
            }
        }
        actual_revenue = float(actual.get("revenue_rmb_bn") or 0.0)
        actual_capex = float(actual.get("capex_rmb_bn") or 0.0)
        capex_to_revenue = (
            max(0.0, actual_capex / actual_revenue)
            if actual_revenue > 0 else 0.0
        )
        for year in (2026, 2027, 2028):
            row = base_rows.get(year) or {}
            revenue = float(row.get("revenue_rmb_bn") or 0.0) * 10.0
            net_income = float(row.get("net_income_rmb_bn") or 0.0) * 10.0
            frozen_fcf = float(row.get("fcfe_rmb_bn") or 0.0) * 10.0
            capex = max(0.0, revenue * capex_to_revenue)
            financials[str(year)] = {
                "revenue": revenue,
                "netIncome": net_income,
                # OCF is an explicit reconciliation bridge: OCF - CapEx = frozen FCFE.
                "ocf": frozen_fcf + capex,
                "capex": capex,
                "equity": (
                    float(row["equity_rmb_bn"]) * 10.0
                    if row.get("equity_rmb_bn") is not None else None
                ),
                "buyback": 0.0,
            }
        row_2028 = financials["2028"]
        bridge_2028 = project_bridge(
            projects,
            2028,
            price=float((base_rows.get(2028) or {}).get(
                "carbonate_price_10k_rmb_t_incl_vat", 13.0
            )),
            income_tax_rate=income_tax_rate,
        )
        fcf_conversion = (
            float(base_rows[2028].get("fcfe_rmb_bn") or 0.0)
            / float(base_rows[2028].get("net_income_rmb_bn") or 1.0)
            if base_rows.get(2028)
            and abs(float(base_rows[2028].get("net_income_rmb_bn") or 0.0)) > 1e-9
            else 0.0
        )
        previous_equity = row_2028.get("equity")
        for year in (2029, 2030):
            bridge = project_bridge(
                projects,
                year,
                price=13.0,
                income_tax_rate=income_tax_rate,
            )
            revenue = max(
                0.0,
                float(row_2028.get("revenue") or 0.0)
                + bridge["revenue"] - bridge_2028["revenue"],
            )
            net_income = bridge["netIncome"]
            fcf = net_income * fcf_conversion
            capex = max(0.0, revenue * capex_to_revenue)
            if previous_equity is not None:
                previous_equity = float(previous_equity) + max(0.0, net_income - fcf)
            financials[str(year)] = {
                "revenue": revenue,
                "netIncome": net_income,
                "ocf": fcf + capex,
                "capex": capex,
                "equity": previous_equity,
                "buyback": 0.0,
            }
        return financials

    for company in model.get("companies") or []:
        ticker = str(company.get("ticker") or "")
        company_recon = recon_by_ticker.get(ticker) or {}
        market = company_recon.get("market_reconciliation") or {}
        assumptions = company.get("assumptions") or {}
        workbook_company = workbook_by_name.get(str(company.get("company")))
        projects = aggregate_projects(company, workbook_company)
        base_rows = {
            int(row["year"]): row
            for row in (company.get("scenarios") or {}).get("基准情景", [])
        }
        pe_range = None
        valuation_rows = []
        valuation_methods = []
        for valuation in company.get("valuations") or []:
            if valuation.get("method") == "正常化市盈率":
                pe_range = (valuation.get("inputs") or {}).get("pe_range")
            inputs = valuation.get("inputs") or {}
            low_value = valuation.get("low_rmb_bn")
            high_value = valuation.get("high_rmb_bn")
            method = str(valuation.get("method") or "")
            formula = ""
            input_summary = ""
            if method == "正常化市盈率":
                net_income = inputs.get("net_income_rmb_bn")
                multiples = inputs.get("pe_range") or []
                if net_income is not None and len(multiples) == 2:
                    formula = (
                        f"股权价值＝{float(net_income) * 10:.2f}亿元归母净利润"
                        f"×{float(multiples[0]):.2f}—{float(multiples[1]):.2f}倍"
                    )
                    input_summary = (
                        f"{valuation.get('forecast_year')}年归母净利润"
                        f"{float(net_income) * 10:.2f}亿元；PE"
                        f"{float(multiples[0]):.2f}—{float(multiples[1]):.2f}倍"
                    )
            elif method == "PB—ROE":
                pb_range = inputs.get("pb_range") or []
                roe_range = inputs.get("sustainable_roe_range_pct") or []
                equity = (base_rows.get(int(valuation.get("forecast_year") or 2027)) or {}).get(
                    "equity_rmb_bn"
                )
                if equity is not None and len(pb_range) == 2:
                    formula = (
                        "合理PB＝（可持续ROE－长期增长率）÷"
                        "（股权成本－长期增长率）；"
                        f"股权价值＝{float(equity) * 10:.2f}亿元期末归母权益"
                        f"×{float(pb_range[0]):.2f}—{float(pb_range[1]):.2f}倍"
                    )
                if len(roe_range) == 2:
                    input_summary = (
                        f"可持续ROE {float(roe_range[0]):.2f}%—"
                        f"{float(roe_range[1]):.2f}%；低值Ke/g＝"
                        f"{float(inputs.get('low_value_cost_of_equity_pct', 0)):.2f}%/"
                        f"{float(inputs.get('low_value_terminal_growth_pct', 0)):.2f}%，"
                        f"高值Ke/g＝"
                        f"{float(inputs.get('high_value_cost_of_equity_pct', 0)):.2f}%/"
                        f"{float(inputs.get('high_value_terminal_growth_pct', 0)):.2f}%"
                    )
            elif method == "股权自由现金流":
                fcfe = inputs.get("fcfe_rmb_bn") or []
                formula = (
                    "股权价值＝ΣFCFEₜ÷(1＋Ke)ᵗ＋"
                    "FCFE₃×(1＋g)÷(Ke－g)÷(1＋Ke)³"
                )
                if fcfe:
                    input_summary = (
                        "2026—2028年FCFE＝"
                        + "/".join(f"{float(value) * 10:.2f}" for value in fcfe)
                        + "亿元；低值Ke/g＝"
                        f"{float(inputs.get('low_value_cost_of_equity_pct', 0)):.2f}%/"
                        f"{float(inputs.get('low_value_terminal_growth_pct', 0)):.2f}%，"
                        "高值Ke/g＝"
                        f"{float(inputs.get('high_value_cost_of_equity_pct', 0)):.2f}%/"
                        f"{float(inputs.get('high_value_terminal_growth_pct', 0)):.2f}%"
                    )
            elif method == "条件化项目NAV":
                formula = (
                    "项目价值只在审批、融资、建设、试车和稳定量产依次完成后成立；"
                    "当前公开数据不足以形成逐年可复算矿山NAV。"
                )
                input_summary = (
                    f"公司项目权益{float(inputs.get('company_project_ownership_pct', 0)):.2f}%；"
                    f"规划产能{float(inputs.get('planned_capacity_10kt', 0)):.2f}万吨"
                )
            market_cap = market.get("market_cap_rmb_bn")
            relative_low = (
                float(low_value) / float(market_cap) - 1.0
                if low_value is not None and market_cap not in (None, 0)
                else None
            )
            relative_high = (
                float(high_value) / float(market_cap) - 1.0
                if high_value is not None and market_cap not in (None, 0)
                else None
            )
            valuation_rows.append(
                {
                    "method": method,
                    "role": valuation.get("role"),
                    "forecastYear": valuation.get("forecast_year"),
                    "lowYi": (
                        float(low_value) * 10.0 if low_value is not None else None
                    ),
                    "highYi": (
                        float(high_value) * 10.0 if high_value is not None else None
                    ),
                    "relativeLow": relative_low,
                    "relativeHigh": relative_high,
                    "formula": formula,
                    "inputSummary": input_summary,
                    "parameterBasis": valuation.get("parameter_basis") or "",
                    "limitation": valuation.get("limitation") or "",
                }
            )
            forecast_year = int(valuation.get("forecast_year") or 2027)
            if method == "正常化市盈率":
                multiples = inputs.get("pe_range") or [10.0, 10.0]
                valuation_methods.append(
                    {
                        "method": method,
                        "role": valuation.get("role") or "核心",
                        "kind": "multiple",
                        "driver": "netIncome",
                        "year": forecast_year,
                        "basisLabel": "情景归母净利润",
                        "parameterLabel": "PE（倍）",
                        "lowParameter": float(multiples[0]),
                        "highParameter": float(multiples[-1]),
                        "formula": "股权价值＝情景归母净利润×PE",
                        "note": valuation.get("parameter_basis") or "",
                    }
                )
            elif method == "PB—ROE":
                roe_range = inputs.get("sustainable_roe_range_pct") or [0.0, 0.0]
                forecast_roe = float(
                    (base_rows.get(forecast_year) or {}).get("roe_pct") or 0.0
                )
                low_factor = (
                    float(roe_range[0]) / forecast_roe
                    if forecast_roe > 0 and len(roe_range) >= 1 else 0.85
                )
                high_factor = (
                    float(roe_range[-1]) / forecast_roe
                    if forecast_roe > 0 and len(roe_range) >= 1 else 1.0
                )
                valuation_methods.append(
                    {
                        "method": method,
                        "role": valuation.get("role") or "有效参考",
                        "kind": "pb_roe",
                        "year": forecast_year,
                        "basisLabel": "期末归母权益与情景ROE",
                        "lowValue": {
                            "roeFactor": low_factor,
                            "costOfEquityPct": float(
                                inputs.get("low_value_cost_of_equity_pct") or 12.5
                            ),
                            "terminalGrowthPct": float(
                                inputs.get("low_value_terminal_growth_pct") or 2.0
                            ),
                        },
                        "highValue": {
                            "roeFactor": high_factor,
                            "costOfEquityPct": float(
                                inputs.get("high_value_cost_of_equity_pct") or 10.5
                            ),
                            "terminalGrowthPct": float(
                                inputs.get("high_value_terminal_growth_pct") or 3.0
                            ),
                        },
                        "formula": (
                            "可持续ROE＝情景ROE×正常化系数；"
                            "合理PB＝（可持续ROE－长期增长率）÷"
                            "（股权成本－长期增长率）；"
                            "股权价值＝期末归母权益×合理PB"
                        ),
                        "note": valuation.get("parameter_basis") or "",
                    }
                )
            elif method == "股权自由现金流":
                valuation_methods.append(
                    {
                        "method": method,
                        "role": valuation.get("role") or "诊断",
                        "kind": "fcfe_dcf",
                        "forecastYears": [2026, 2027, 2028],
                        "basisLabel": "情景自由现金流",
                        "lowValue": {
                            "costOfEquityPct": float(
                                inputs.get("low_value_cost_of_equity_pct") or 12.5
                            ),
                            "terminalGrowthPct": float(
                                inputs.get("low_value_terminal_growth_pct") or 2.0
                            ),
                        },
                        "highValue": {
                            "costOfEquityPct": float(
                                inputs.get("high_value_cost_of_equity_pct") or 10.5
                            ),
                            "terminalGrowthPct": float(
                                inputs.get("high_value_terminal_growth_pct") or 3.0
                            ),
                        },
                        "formula": (
                            "股权价值＝预测期自由现金流折现值＋"
                            "终值折现值；必须满足股权成本大于长期增长率"
                        ),
                        "note": valuation.get("parameter_basis") or "",
                    }
                )
            else:
                valuation_methods.append(
                    {
                        "method": method,
                        "role": valuation.get("role") or "诊断",
                        "kind": "frozen",
                        "low": (
                            float(low_value) * 10.0
                            if low_value is not None else None
                        ),
                        "high": (
                            float(high_value) * 10.0
                            if high_value is not None else None
                        ),
                        "basisLabel": "冻结条件估值",
                        "formula": formula,
                        "note": valuation.get("parameter_basis") or "",
                    }
                )
        financials = build_financial_bridge(
            company,
            base_rows,
            projects,
            income_tax_rate=0.15,
        )
        companies.append(
            {
                "companyKey": str(company["research_company_id"]),
                "companyId": int(company["research_company_id"]),
                "name": company["company"],
                "ticker": ticker,
                "modelType": company.get("model_type"),
                "currentPrice": market.get("price_cny"),
                "marketCapYi": (
                    float(market["market_cap_rmb_bn"]) * 10.0
                    if market.get("market_cap_rmb_bn") is not None else None
                ),
                "actual2025ProfitYi": (
                    float((company.get("actual_2025") or {}).get(
                        "net_income_rmb_bn", 0.0
                    )) * 10.0
                ),
                "independent2026ProfitYi": (
                    float((base_rows.get(2026) or {}).get(
                        "net_income_rmb_bn", 0.0
                    )) * 10.0
                ),
                "consensus2026ProfitYi": (
                    float(
                        (((company_recon.get("yearly_reconciliation") or [{}])[0]
                          .get("wind_consensus") or {})
                         .get("net_income_rmb_bn"))
                    ) * 10.0
                    if (
                        company_recon.get("yearly_reconciliation")
                        and (((company_recon["yearly_reconciliation"][0]
                              .get("wind_consensus") or {})
                             .get("net_income_rmb_bn")) is not None)
                    ) else None
                ),
                "defaultPrice": 13.0,
                "incomeTaxRatePct": 15.0,
                # Retained temporarily for old exported scenario readers.
                "afterTaxFactor": 0.85,
                "targetPe": (
                    sum(float(value) for value in pe_range) / len(pe_range)
                    if pe_range else 10.0
                ),
                "targetPeLow": (
                    float(pe_range[0]) if pe_range and len(pe_range) == 2 else 10.0
                ),
                "targetPeHigh": (
                    float(pe_range[1]) if pe_range and len(pe_range) == 2 else 10.0
                ),
                "valuationRows": valuation_rows,
                "valuationMethods": valuation_methods,
                "financials": financials,
                "cashConversion": 1.0,
                "payoutByYear": {str(year): 0.0 for year in years},
                "financialBridgeNote": (
                    "2025年经营现金流与资本开支为实际值；2026—2028年"
                    "自由现金流取冻结独立模型，经营现金流按“自由现金流＋"
                    "资本开支”反推，资本开支以2025年资本开支/收入比例桥接。"
                    "它们是可编辑建模输入，不是Wind/Tushare未来财务事实。"
                ),
                "valuationModelHash": model.get("content_sha256"),
                "projects": projects,
                "evidence": company.get("project_and_operating_evidence") or [],
                "modelFrozenBeforeReconciliation": bool(
                    (company.get("freeze") or {}).get(
                        "frozen_before_external_reconciliation"
                    )
                ),
                "formula": {
                    "resource_profit": (
                        "资源税后利润＝Σ[项目总产量×利润归属比例×"
                        "(含税锂价÷1.13－含税完全成本÷1.13)]×"
                        "(1－企业所得税率)"
                    ),
                    "processing_profit": (
                        "加工税后利润＝Σ[权益加工量×含税单位加工利润"
                        "÷1.13]×(1－企业所得税率)"
                    ),
                    "net_income": (
                        "归母净利润＝资源税后利润＋加工税后利润＋"
                        "净利润口径其他业务与公司层调整"
                    ),
                },
                "limitation": company.get("limitations") or [],
                "workbookProjectLedger": bool(workbook_company),
                "workbookProjectCount": (
                    int(workbook_company.get("projectCount") or 0)
                    if workbook_company else 0
                ),
                "workbookNotes": (
                    (workbook_company.get("workbookNotes") or [])
                    if workbook_company else []
                ),
                "sheet1Baseline2024": sheet1_resource_baseline_2024.get(
                    ticker
                ),
            }
        )
        company_names.add(str(company.get("company")))

    # Preserve workbook companies that are outside the 13-company lithium
    # research set.  They remain editable calculator cases; a company page link
    # is provided only when the canonical security already exists.
    for workbook_company in project_ledger.get("companies") or []:
        name = str(workbook_company.get("name") or "")
        if not name or name in company_names:
            continue
        ticker = str(workbook_company.get("ticker") or "")
        listed = query_one(
            "SELECT id, name, ticker FROM company "
            "WHERE ticker=? OR name=? ORDER BY CASE WHEN ticker=? THEN 0 ELSE 1 END "
            "LIMIT 1",
            (ticker, name, ticker),
        )
        company_id = int(listed["id"]) if listed else None
        current_price = None
        market_cap = None
        actual_profit = None
        if company_id is not None:
            try:
                bundle = financial_company_bundle(
                    company_id, db_path=FINANCIAL_DB_PATH
                ) or {}
                snapshot = {
                    str(row.get("metric_name")): row
                    for row in (
                        (bundle.get("valuation_summary") or {}).get(
                            "current_snapshot"
                        ) or []
                    )
                }
                current_price = (
                    snapshot.get("close") or {}
                ).get("value_num")
                market_cap = (
                    snapshot.get("market_cap_cny") or {}
                ).get("value_num")
            except Exception:
                log.exception(
                    "计算器读取工作簿扩展公司财务失败 company_id=%s",
                    company_id,
                )
        companies.append(
            {
                "companyKey": (
                    str(company_id) if company_id is not None
                    else f"ticker:{ticker}"
                ),
                "companyId": company_id,
                "name": name,
                "ticker": ticker,
                "modelType": "Excel逐项目资源模型",
                "currentPrice": current_price,
                "marketCapYi": market_cap,
                "actual2025ProfitYi": actual_profit,
                "independent2026ProfitYi": None,
                "consensus2026ProfitYi": None,
                "defaultPrice": 13.0,
                "incomeTaxRatePct": 15.0,
                "afterTaxFactor": 0.85,
                "targetPe": 10.0,
                "targetPeLow": 10.0,
                "targetPeHigh": 10.0,
                "valuationRows": [],
                "valuationMethods": [
                    {
                        "method": "研究员情景市盈率",
                        "role": "诊断",
                        "kind": "multiple",
                        "driver": "netIncome",
                        "year": 2030,
                        "basisLabel": "项目模型归母净利润",
                        "parameterLabel": "PE（倍）",
                        "lowParameter": 10.0,
                        "highParameter": 10.0,
                        "formula": "股权价值＝情景归母净利润×研究员输入PE",
                        "note": (
                            "该扩展公司没有完整独立财务模型，默认倍数只用于"
                            "网页情景，不代表研究结论。"
                        ),
                    }
                ],
                "financials": {
                    str(year): {
                        "revenue": 0.0,
                        "netIncome": 0.0,
                        "ocf": 0.0,
                        "capex": 0.0,
                        "equity": None,
                        "buyback": 0.0,
                    }
                    for year in years
                },
                "cashConversion": 1.0,
                "payoutByYear": {str(year): 0.0 for year in years},
                "financialBridgeNote": (
                    "该扩展公司只有项目底稿，没有可复核的公司层未来现金流"
                    "基准；财务输入默认为零，需由研究员补充后才能使用。"
                ),
                "valuationModelHash": model.get("content_sha256"),
                "projects": [
                    project_template_compat(project_from_workbook(row))
                    for row in workbook_company.get("projects") or []
                ],
                "evidence": [
                    "逐矿山/盐湖项目参数来自参考模型底稿；网页按本项目自身"
                    "权益重新计算。"
                ],
                "modelFrozenBeforeReconciliation": True,
                "formula": {
                    "resource_profit": (
                        "资源税后利润＝Σ[项目总产量×利润归属比例×"
                        "(含税锂价÷1.13－含税完全成本÷1.13)]×"
                        "(1－企业所得税率)"
                    ),
                    "processing_profit": (
                        "加工税后利润＝Σ[权益加工量×含税单位加工利润"
                        "÷1.13]×(1－企业所得税率)"
                    ),
                    "net_income": (
                        "归母净利润＝资源税后利润＋加工税后利润＋"
                        "净利润口径其他业务与公司层调整"
                    ),
                },
                "limitation": [
                    "该公司不在本轮13家公司独立盈利模型中，当前页面只恢复"
                    "Excel资源项目；非锂业务和公司层费用需要研究员另行添加。"
                ],
                "workbookProjectLedger": True,
                "workbookProjectCount": int(
                    workbook_company.get("projectCount") or 0
                ),
                "workbookNotes": (
                    workbook_company.get("workbookNotes") or []
                ),
                "sheet1Baseline2024": sheet1_resource_baseline_2024.get(
                    ticker
                ),
            }
        )
        company_names.add(name)

    companies.sort(
        key=lambda row: (
            0 if row.get("workbookProjectLedger") else 1,
            str(row.get("ticker") or ""),
        )
    )
    selected_company_id = request.args.get("company_id", type=int)
    selected_key = (
        str(selected_company_id)
        if selected_company_id is not None
        else str((companies[0] if companies else {}).get("companyKey") or "")
    )
    return render_template(
        "lithium_calculator.html",
        calculator_companies_json=json.dumps(companies, ensure_ascii=False),
        selected_company_key=selected_key,
        calculator_years_json=json.dumps(years),
        calculator_years=years,
        model_as_of=model.get("as_of_date"),
        workbook_sha256=str(
            project_ledger.get("source_workbook_sha256") or ""
        ),
        comparison_mode=comparison_mode,
    )


@app.route("/company/<int:company_id>")
def company_tag(company_id: int):
    """公司透视统一页:画像 + 六项核心财务指标 + 股价/散户情绪/发帖量 + 行业 tag。
    所有公司超链接的落点。研究类数据 research.db 只读;情绪/价格 sentiment.db。"""
    co = query_one("SELECT * FROM company WHERE id=?", (company_id,))
    if not co:
        canonical = query_one(
            "SELECT canonical_company_id FROM company_identity_redirect WHERE old_company_id=?",
            (company_id,),
        ) if _table_exists("company_identity_redirect") else None
        if canonical:
            return redirect(url_for(
                "company_tag", company_id=int(canonical["canonical_company_id"]),
                **request.args.to_dict(flat=True),
            ), code=301)
        abort(404)
    try:
        financial_bundle = financial_company_bundle(company_id, db_path=FINANCIAL_DB_PATH)
    except Exception:
        log.exception("读取 financial.db 公司数据失败 company_id=%s", company_id)
        financial_bundle = None
    valuation_tracker_member = None
    if (
        VALUATION_TRACKER_REPOSITORY is not None
        and not (financial_bundle or {}).get("valuation_model_runs")
    ):
        try:
            valuation_tracker_member = (
                VALUATION_TRACKER_REPOSITORY.member_by_company_id(company_id)
            )
        except Exception:
            log.exception("读取公司估值跟踪版本失败 company_id=%s", company_id)
    requested_industry = request.args.get("industry_id", type=int)
    if requested_industry:
        profile = query_one(
            """SELECT cp.* FROM company_profile cp
               WHERE cp.company_id=? AND cp.industry_id=? ORDER BY cp.id DESC LIMIT 1""",
            (company_id, requested_industry),
        )
    else:
        profile = query_one(
            """SELECT cp.*
               FROM company_profile cp
               LEFT JOIN company_industry ci
                 ON ci.company_id=cp.company_id AND ci.industry_id=cp.industry_id
               WHERE cp.company_id=?
               ORDER BY CASE WHEN COALESCE(ci.role,'') LIKE '%主营%'
                                  OR COALESCE(ci.role,'') LIKE '%核心%' THEN 0 ELSE 1 END,
                        ci.revenue_share IS NULL, ci.revenue_share DESC,
                        cp.industry_id ASC, cp.id DESC LIMIT 1""",
            (company_id,),
        )
    industries = query_all("""
        SELECT ci.*, i.name AS industry_name, i.tier
        FROM company_industry ci JOIN industry i ON i.id = ci.industry_id
        WHERE ci.company_id=? ORDER BY ci.revenue_share DESC""", (company_id,))
    # 核心(主)行业:company_profile.industry_id 为权威主产业;缺则取首个
    core_ind_id = (profile["industry_id"] if (profile and profile["industry_id"]) else
                   (industries[0]["industry_id"] if industries else None))
    peer_asset_return_rows = []
    peer_asset_return_summary = None
    peer_asset_return_note = "尚未形成可审计的同行资产回报样本。"
    if core_ind_id and financial_bundle:
        peer_ids, peer_asset_return_note = _asset_return_peer_candidates(
            company_id, core_ind_id, profile,
        )
        try:
            if peer_ids:
                peer_asset_return_rows = financial_peer_asset_return_rows(
                    peer_ids, db_path=FINANCIAL_DB_PATH,
                )
                peer_asset_return_summary = _asset_return_peer_summary(
                    peer_asset_return_rows, company_id,
                )
                # 一个公司自身不能构成同行截面。仍由上方当前值卡片展示本公司。
                if len(peer_asset_return_rows) < 2:
                    peer_asset_return_rows = []
                    peer_asset_return_note += " 当前满足条件且有数据的公司不足两家，暂不形成横截面对照。"
        except Exception:
            log.exception("读取同行资产回报截面失败 company_id=%s", company_id)
    is_pcb_equipment = any(
        row.get("industry_id") == core_ind_id and row.get("industry_name") == "PCB专用设备"
        for row in industries
    )
    themes = query_all("""
        SELECT tc.*, t.name AS theme_name FROM theme_company tc
        JOIN theme t ON t.id = tc.theme_id WHERE tc.company_id=?""", (company_id,))
    shares = query_all("""SELECT sub_market, geo, share, share_as_of, rank, credibility, display_note
        FROM company_sub_market_share WHERE company_id=? ORDER BY share DESC""", (company_id,)) \
        if _table_exists("company_sub_market_share") else []
    # 画像 JSON 字段
    rev = _json_or([], profile.get("revenue_series")) if profile else []
    ni = _json_or([], profile.get("net_income_series")) if profile else []
    if financial_bundle:
        canonical_rev: list[dict[str, Any]] = []
        canonical_ni: list[dict[str, Any]] = []
        for row in financial_bundle.get("historical_table") or []:
            period = str(row.get("period") or "")
            metrics = row.get("metrics") or {}
            if metrics.get("revenue"):
                canonical_rev.append({"period": period, **metrics["revenue"]})
            if metrics.get("net_income"):
                canonical_ni.append({"period": period, **metrics["net_income"]})
        if canonical_rev or canonical_ni:
            rev, ni = canonical_rev, canonical_ni
    for i in range(1, len(rev)):                       # 只补相邻完整年度 YoY；季度同比必须使用上年同期
        previous_period = str(rev[i - 1].get("period") or "")
        current_period = str(rev[i].get("period") or "")
        comparable_full_years = bool(
            re.fullmatch(r"\d{4}", previous_period)
            and re.fullmatch(r"\d{4}", current_period)
            and int(current_period) == int(previous_period) + 1
        )
        if (
            comparable_full_years
            and rev[i].get("yoy") is None
            and rev[i - 1].get("value")
            and rev[i].get("value")
        ):
            try:
                rev[i]["yoy"] = round((float(rev[i]["value"]) / float(rev[i - 1]["value"]) - 1) * 100, 1)
            except Exception:
                pass
    events = _json_or([], profile.get("recent_events")) if profile else []
    if is_pcb_equipment:
        events = _pcb_public_recent_events(events)
    risks = _json_or([], profile.get("risks")) if profile else []
    metric_cards = _company_metric_cards(
        co,
        profile,
        strict_financial_source=is_pcb_equipment,
        financial_bundle=financial_bundle,
    )
    financial_rows = _aligned_company_financial_rows(rev, ni)
    financial_figure = _company_financial_figure(rev, ni)
    asset_return_figures = _asset_return_figures(financial_bundle)
    opportunity_links = _company_opportunity_links(company_id, co.get("ticker"))
    financial_summary = {}
    lithium_calculator_ready = False
    if financial_bundle:
        current_metrics = financial_bundle.get("current_metrics") or {}
        financial_summary = {
            metric: current_metrics.get(metric)
            for metric in (
                "market_cap_cny", "market_cap_usd", "pe_ttm", "pb", "roe", "roa",
            )
            if current_metrics.get(metric)
        }
        lithium_calculator_ready = any(
            str(run.get("research_run_ref") or "")
            == "btrack_lithium_and_carbonate_20260727"
            for run in (financial_bundle.get("model_runs") or [])
        )
    # 公司定向情报新闻:页面只显示 近3月重要性「高」+ 近1月重要性「中」;其余进「全部新闻」页
    from datetime import date as _date, timedelta as _td
    _t = _date.today()
    cut3 = (_t - _td(days=92)).isoformat(); cut1 = (_t - _td(days=31)).isoformat()
    news_all = senti_all("""SELECT title, url, source, published_at, sentiment, materiality, summary_ai
        FROM event_item WHERE entity_type='company' AND entity_id=? ORDER BY published_at DESC""", (company_id,))
    news = [e for e in news_all if (e["materiality"] == "高" and (e["published_at"] or "")[:10] >= cut3)
            or (e["materiality"] == "中" and (e["published_at"] or "")[:10] >= cut1)]
    news_more = len(news_all) - len(news)
    # 近期股价走势 + 散户情绪 + 散户发帖量；V2 与 legacy 按切换日期连续拼接。
    panels = _company_panels(company_id)
    rb = _company_retail_summary_rows(company_id)

    latest_retail = _latest_retail_summary_row(rb)
    r_net = None
    if latest_retail:
        r_net = latest_retail.get("net_weighted")
        if r_net is None:
            r_net = latest_retail.get("net_plain")
    senti_summ = {
        "retail_latest": r_net,
        "retail_cov": latest_retail.get("coverage") if latest_retail else None,
        # usable 保留严格审计口径；页面是否提示“未完成”使用与图表一致的
        # display_ready（评分完成 + 样本显著），不被 Xinghan/K 线附加源失败拖低。
        "retail_usable": bool(latest_retail and latest_retail.get("usable")),
        "retail_display_ready": bool(latest_retail and latest_retail.get("display_ready")),
        "retail_quality_label": (
            None
            if not latest_retail or latest_retail.get("display_ready")
            else ("低样本" if latest_retail.get("score_complete") else "评分进行中")
        ),
        "retail_mode": latest_retail.get("mode") if latest_retail else None,
        "retail_valid": sum(r.get("scored_count") or 0 for r in rb),
        "heat_total": sum(r.get("raw_count") or 0 for r in rb),
        "has_price": panels.get("has_window_price") or panels.get("has_daily_price"),
    }
    return render_template("company_tag.html", co=co, profile=profile, industries=industries,
                           core_ind_id=core_ind_id, themes=themes, shares=shares, rev=rev, ni=ni,
                           events=events, risks=risks, news=news, news_more=news_more,
                           metric_cards=metric_cards,
                           financial_rows=financial_rows,
                           financial_bundle=financial_bundle,
                           valuation_tracker_member=valuation_tracker_member,
                           financial_summary=financial_summary,
                           asset_return=asset_return_figures,
                           asset_return_peers=peer_asset_return_rows,
                           asset_return_peer_summary=peer_asset_return_summary,
                           asset_return_peer_note=peer_asset_return_note,
                           opportunity_links=opportunity_links,
                           lithium_calculator_ready=lithium_calculator_ready,
                           is_pcb_equipment=is_pcb_equipment,
                           financial_figure_json=json.dumps(financial_figure),
                           pb_roe_figure_json=json.dumps(asset_return_figures.get("pb_roe")),
                           pb_roa_figure_json=json.dumps(asset_return_figures.get("pb_roa")),
                           pb_history_figure_json=json.dumps(asset_return_figures.get("pb_history")),
                           pb_band_figure_json=json.dumps(asset_return_figures.get("pb_price_band")),
                           pe_band_figure_json=json.dumps(asset_return_figures.get("pe_price_band")),
                           roe_path_figure_json=json.dumps(asset_return_figures.get("roe_path")),
                           scenario_workbench_json=json.dumps(
                               (financial_bundle or {}).get("scenario_workbench")
                           ),
                           senti_summ=senti_summ, panels_json=json.dumps(panels))


@app.route("/company/<int:company_id>/news")
def company_news_all(company_id: int):
    """单公司全部情报新闻(cninfo + DeepSeek 打分 + 简评),不做时间/重要性过滤。"""
    co = query_one("SELECT * FROM company WHERE id=?", (company_id,))
    if not co:
        canonical = query_one(
            "SELECT canonical_company_id FROM company_identity_redirect WHERE old_company_id=?",
            (company_id,),
        ) if _table_exists("company_identity_redirect") else None
        if canonical:
            return redirect(url_for(
                "company_news_all", company_id=int(canonical["canonical_company_id"])
            ), code=301)
        abort(404)
    news = senti_all("""SELECT title, url, source, published_at, sentiment, materiality, summary_ai
        FROM event_item WHERE entity_type='company' AND entity_id=? ORDER BY published_at DESC""", (company_id,))
    return render_template("company_news.html", co=co, news=news)


# ── 路由:主题详情页 ──────────────────────────────────
@app.route("/theme/<theme_id>")
def theme_detail(theme_id: str):
    th = query_one("SELECT * FROM theme WHERE id=?", (theme_id,))
    if not th:
        abort(404)
    industries = query_all("""
        SELECT ti.*, i.name AS industry_name FROM theme_industry ti
        JOIN industry i ON i.id = ti.industry_id WHERE ti.theme_id=?
    """, (theme_id,))
    companies = query_all("""
        SELECT tc.*, c.name AS company_name FROM theme_company tc
        JOIN company c ON c.id = tc.company_id WHERE tc.theme_id=?
    """, (theme_id,))
    md_path = DOCS_DIR / "themes" / f"{th['name']}.md"
    doc = load_md(md_path)
    return render_template(
        "theme.html",
        th=th, industries=industries, companies=companies, doc=doc
    )


# ── 路由:PDF 直接 serve ─────────────────────────────
@app.route("/pdf/<int:source_id>")
def serve_pdf(source_id: int):
    src = query_one("SELECT file_path FROM source WHERE id=?", (source_id,))
    if not src or not src.get("file_path"):
        abort(404, "该 source 无 file_path")
    rel = src["file_path"].strip()
    try:
        pdf_abs = resolve_content_reference(
            RUNTIME_LAYOUT.content_root,
            rel,
            default_prefix="papers",
        )
    except ValueError:
        log.warning("serve_pdf 路径越界: %s", rel)
        abort(403)
    # 安全校验:必须在 papers/ 内
    try:
        pdf_abs.relative_to(PAPERS_DIR.resolve())
    except ValueError:
        log.warning(f"serve_pdf 路径越界: {pdf_abs}")
        abort(403)
    if not pdf_abs.exists():
        abort(404)
    return send_from_directory(str(pdf_abs.parent), pdf_abs.name)


# ── 路由:Source JSON API(trace modal 用)─────────────
@app.route("/api/source/<int:source_id>")
def api_source(source_id: int):
    """前端 trace modal 用:返回 source 的轻量 metadata。
    任何页面的溯源按钮 / ^src:N 上标都调本接口取元数据。
    """
    src = query_one("SELECT * FROM source WHERE id=?", (source_id,))
    if not src:
        return jsonify({"ok": False, "error": f"source #{source_id} 不存在"}), 404
    has_pdf = bool(src.get("file_path"))
    url_val = src.get("source_url") or src.get("url")
    detail_url = url_for("source_detail", source_id=src["id"])
    # 该 source 的全部原文摘录(让任意 ^src 上标点开即可直接看到原文,而非"请前往 source 页")
    ex_rows = query_all("""
        SELECT dp.id AS dp_id, dp.industry_id, dp.metric, dp.source_excerpt,
               dp.as_of_date, dp.period, i.name AS industry_name
        FROM industry_data_point dp
        LEFT JOIN industry i ON i.id = dp.industry_id
        WHERE dp.source_id=? AND dp.source_excerpt IS NOT NULL AND TRIM(dp.source_excerpt) <> ''
        ORDER BY dp.industry_id, dp.id
    """, (source_id,))
    excerpts = [{
        "dp_id": r["dp_id"], "industry_id": r["industry_id"],
        "industry_name": r["industry_name"], "metric": r["metric"],
        "excerpt": r["source_excerpt"], "as_of": r["as_of_date"] or r["period"] or "",
        # 每条摘录可深链到 source 详情页并高亮对应数据点行
        "hl_url": detail_url + "?hl=" + str(r["dp_id"]),
    } for r in ex_rows]
    return jsonify({
        "ok": True,
        "id": src["id"],
        "title": src["title"],
        "source_type": src["source_type"],
        "source_type_display": t(src["source_type"]),
        "publisher": src.get("publisher"),
        "author": src.get("author"),
        "publish_date": src.get("publish_date"),
        "quality_tier": src["quality_tier"],
        "value_layer": src.get("value_layer"),
        "is_forward_looking": bool(src.get("is_forward_looking")),
        "is_ai_synth": src["source_type"] == "claude_lit_review",
        "url": url_val,
        "has_pdf": has_pdf,
        "pdf_url": url_for("serve_pdf", source_id=src["id"]) if has_pdf else None,
        "detail_url": detail_url,
        "note": src.get("note"),
        "excerpts": excerpts,
        "excerpt_count": len(excerpts),
    })


# ── 路由:数据点全览 ─────────────────────────────────
@app.route("/data_points")
def data_points_index():
    """全库 industry_data_point 浏览页。
    支持 GET filter: ?tier=1|2|3 &metric=substring &forecast=0|1 &sentiment=看涨|看跌|中性|不适用
    按 industry 分组。空 db 走 empty_state。
    """
    tier      = (request.args.get("tier") or "").strip()
    metric_q  = (request.args.get("metric") or "").strip()
    forecast  = (request.args.get("forecast") or "").strip()
    sentiment = (request.args.get("sentiment") or "").strip()
    em        = (request.args.get("em") or "").strip()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    page_size = 100

    from_sql = """
        FROM industry_data_point dp
        LEFT JOIN source s ON s.id = dp.source_id
        LEFT JOIN industry i ON i.id = dp.industry_id
        WHERE 1=1
    """
    where_sql = ""
    params: List[Any] = []
    if tier in ("1", "2", "3"):
        where_sql += " AND s.quality_tier = ?"
        params.append(int(tier))
    if metric_q:
        where_sql += " AND dp.metric LIKE ?"
        params.append(f"%{metric_q}%")
    if forecast in ("0", "1"):
        where_sql += " AND dp.is_forecast = ?"
        params.append(int(forecast))
    if sentiment in ("看涨", "看跌", "中性", "不适用"):
        where_sql += " AND dp.sentiment = ?"
        params.append(sentiment)
    if em in ("pdf_direct", "web_fetch", "template_estimate", "inferred", "unknown"):
        where_sql += " AND dp.extraction_method = ?"
        params.append(em)

    total = int((query_one(
        "SELECT COUNT(*) AS n " + from_sql + where_sql, tuple(params)
    ) or {}).get("n") or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)

    sql = """
        SELECT dp.*,
               s.title AS source_title,
               s.quality_tier AS source_tier,
               s.source_type AS source_type,
               s.publisher AS source_publisher,
               s.publish_date AS source_publish_date,
               s.file_path AS source_file_path,
               i.name AS industry_name
    """
    sql += from_sql + where_sql
    sql += " ORDER BY i.name ASC, dp.metric ASC, dp.period DESC LIMIT ? OFFSET ?"

    rows = query_all(sql, tuple([*params, page_size, (page - 1) * page_size]))

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        key = r.get("industry_name") or "(无关联行业)"
        grouped.setdefault(key, []).append(r)

    # 全量指标通过搜索框查询；这里只显示高频入口，避免生成巨型 DOM。
    popular_metrics = [
        r["metric"] for r in query_all(
            "SELECT metric, COUNT(*) AS n FROM industry_data_point "
            "GROUP BY metric ORDER BY n DESC, metric ASC LIMIT 100"
        )
    ]

    # 全库 extraction_method 计数(用于 pill 显示数量)
    em_counts: Dict[str, int] = {"pdf_direct": 0, "web_fetch": 0, "template_estimate": 0, "inferred": 0, "unknown": 0}
    for r in query_all("SELECT extraction_method, COUNT(*) c FROM industry_data_point GROUP BY extraction_method"):
        em_counts[r["extraction_method"]] = r["c"]

    # ── 数据概览图(Plotly · 全库,不随筛选变)──
    # (1) 来源构成 extraction_method:可视化数据 provenance(抗 slop 透明化)
    # (2) 各行业数据点数
    overview_charts: Dict[str, str] = {}
    if _PLOTLY_OK:
        em_order = [("pdf_direct", "原文精读", "#16a34a"), ("web_fetch", "网搜", "#2563eb"),
                    ("inferred", "推算", "#0891b2"), ("template_estimate", "模板估(降级)", "#f59e0b"),
                    ("unknown", "未标", "#94a3b8")]
        trips = [(lab, em_counts.get(k, 0), col) for k, lab, col in em_order if em_counts.get(k, 0) > 0]
        trips.sort(key=lambda x: x[1], reverse=True)
        if trips:
            overview_charts["em"] = _hbar_div(
                [x[0] for x in trips], [x[1] for x in trips], [str(x[1]) for x in trips],
                colors=[x[2] for x in trips], height=max(150, 36 * len(trips) + 38))
        ind_rows = query_all(
            "SELECT i.name AS name, COUNT(*) AS n FROM industry_data_point dp "
            "LEFT JOIN industry i ON i.id=dp.industry_id WHERE i.name IS NOT NULL "
            "GROUP BY dp.industry_id ORDER BY n DESC")
        if ind_rows:
            top = ind_rows[:12]
            overview_charts["by_ind"] = _hbar_div(
                [r["name"] for r in top], [r["n"] for r in top], [str(r["n"]) for r in top],
                color="#0d9488", height=max(150, 32 * len(top) + 38))

    return render_template(
        "data_points.html",
        grouped=grouped,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        filter_tier=tier,
        filter_metric=metric_q,
        filter_forecast=forecast,
        filter_sentiment=sentiment,
        filter_em=em,
        em_counts=em_counts,
        overview_charts=overview_charts,
        all_metrics=popular_metrics,
    )


# ── 路由:Source 库 ─────────────────────────────────
@app.route("/sources")
def sources_index():
    """全库 source 浏览页。按 quality_tier 分组。
    点击进 source_detail。空 db 走 empty_state。
    """
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    page_size = 100
    total = int((query_one("SELECT COUNT(*) AS n FROM source") or {}).get("n") or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    rows = query_all("""
        SELECT s.*,
               (SELECT COUNT(*) FROM source_entity se WHERE se.source_id = s.id) AS entity_count,
               (SELECT COUNT(*) FROM industry_data_point dp WHERE dp.source_id = s.id) AS data_point_count
        FROM source s
        ORDER BY s.quality_tier ASC, s.publish_date DESC
        LIMIT ? OFFSET ?
    """, (page_size, (page - 1) * page_size))
    grouped: Dict[int, List[Dict[str, Any]]] = {1: [], 2: [], 3: []}
    for r in rows:
        grouped.setdefault(r["quality_tier"], []).append(r)
    return render_template(
        "sources.html", grouped=grouped, total=total, page=page,
        page_size=page_size, total_pages=total_pages,
    )


# ── 路由:增量更新批次列表(任务 6c)──────────────────
@app.route("/incremental")
def incremental_index():
    """所有 source_snapshot 列表 + 待 review 的 md_section_version。
    给用户 review 增量更新动作用。
    """
    snapshots = query_all("""
        SELECT ss.*, i.name AS industry_name
        FROM source_snapshot ss
        LEFT JOIN industry i ON i.id = ss.industry_id
        ORDER BY ss.snapshot_date DESC
    """)
    # JSON 解析 new_source_ids
    for s in snapshots:
        ids_raw = s.get("new_source_ids")
        if ids_raw:
            try:
                s["new_source_ids_list"] = json.loads(ids_raw)
            except Exception:
                s["new_source_ids_list"] = []
        else:
            s["new_source_ids_list"] = []

    pending = query_all("""
        SELECT * FROM md_section_version
        WHERE review_pending=1
        ORDER BY last_updated DESC
    """)
    return render_template(
        "incremental.html",
        snapshots=snapshots,
        pending=pending,
    )


# ── 路由:触发增量更新(任务 6a)──────────────────────
@app.route("/refresh/<int:industry_id>", methods=["GET", "POST"])
def refresh_industry(industry_id: int):
    """触发增量更新流程。
    GET:渲染确认页(显示当前 industry 状态 + 即将扫描的目录 + 上次快照)。
    POST:跑 tools/pipeline/incremental_update.py --industry <id> --dry-run。
          实际抽 claim 仍需 SCIENTIST session 跑(本路由仅扫描 + 列差异)。
    """
    ind = query_one("SELECT * FROM industry WHERE id=?", (industry_id,))
    if not ind:
        abort(404, f"industry id={industry_id} 不存在")

    last_snap = query_one(
        "SELECT * FROM source_snapshot WHERE industry_id=? "
        "ORDER BY snapshot_date DESC LIMIT 1",
        (industry_id,),
    )

    if request.method == "POST":
        script = ROOT / "tools" / "pipeline" / "incremental_update.py"
        cmd = [sys.executable, str(script), "--industry", str(industry_id), "--dry-run"]
        try:
            proc = subprocess.run(
                cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace",
            )
            return render_template(
                "refresh_result.html",
                ind=ind,
                cmd=" ".join(cmd),
                stdout=proc.stdout,
                stderr=proc.stderr,
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return render_template(
                "refresh_result.html",
                ind=ind, cmd=" ".join(cmd),
                stdout="", stderr="脚本执行超时(60s)", returncode=-1,
            )
        except Exception as e:
            log.error(f"refresh exec failed: {traceback.format_exc()}")
            return render_template(
                "refresh_result.html",
                ind=ind, cmd=" ".join(cmd),
                stdout="", stderr=f"执行异常:{e}", returncode=-1,
            )

    # GET:确认页
    papers_subdir = PAPERS_DIR / ind["name"]
    paper_files: List[str] = []
    if papers_subdir.exists():
        for p in sorted(papers_subdir.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                rel = p.relative_to(PAPERS_DIR)
                paper_files.append(str(rel).replace("\\", "/"))

    # 已入库的 file_path 集合
    db_files = set()
    for s in query_all("SELECT file_path FROM source WHERE file_path IS NOT NULL"):
        if s.get("file_path"):
            db_files.add(s["file_path"].replace("\\", "/").lstrip("/"))

    # 新文件 = 在 papers/ 内但不在 db file_path 集合中
    new_files = []
    for rel in paper_files:
        full_rel = f"papers/{rel}"
        if full_rel not in db_files and rel not in db_files:
            new_files.append(rel)

    return render_template(
        "refresh_confirm.html",
        ind=ind,
        last_snap=last_snap,
        papers_subdir=(
            str(papers_subdir.relative_to(RUNTIME_LAYOUT.content_root))
            if papers_subdir.exists()
            else None
        ),
        paper_files=paper_files,
        new_files=new_files,
    )


# ── 路由:抽取审计 /audit/extraction(任务 1c)──────────
@app.route("/audit/extraction")
def audit_extraction():
    """显示所有 source 抽取达标状态。
    - 零数据 source 红色高亮
    - 不达标 source 橙色
    - 达标 source 绿色
    SCIENTIST 用此页随时查缺口。
    """
    rows = query_all("""
        SELECT id, title, source_type, value_layer, quality_tier,
               publish_date, publisher,
               dp_count, ka_count_approx, dp_min, ka_min
        FROM v_source_extraction_audit
        ORDER BY (CASE WHEN dp_count = 0 THEN 0
                       WHEN dp_count < dp_min THEN 1
                       ELSE 2 END),
                 dp_count ASC, id ASC
    """)
    grouped = {"zero": [], "short": [], "ok": []}
    for r in rows:
        if r["dp_count"] == 0:
            r["status"] = "zero"
            grouped["zero"].append(r)
        elif r["dp_count"] < r["dp_min"] or r["ka_count_approx"] < r["ka_min"]:
            r["status"] = "short"
            grouped["short"].append(r)
        else:
            r["status"] = "ok"
            grouped["ok"].append(r)
    totals = {
        "total": len(rows),
        "zero":  len(grouped["zero"]),
        "short": len(grouped["short"]),
        "ok":    len(grouped["ok"]),
    }

    # 加 extraction_method 分布(全表)+ 按 industry
    em_overall = {"pdf_direct": 0, "web_fetch": 0, "template_estimate": 0, "inferred": 0, "unknown": 0}
    for r in query_all("SELECT extraction_method, COUNT(*) c FROM industry_data_point GROUP BY extraction_method"):
        em_overall[r["extraction_method"]] = r["c"]

    em_by_industry = []
    for r in query_all("""
        SELECT i.id, i.name, i.tier, i.status,
               SUM(CASE WHEN d.extraction_method='pdf_direct' THEN 1 ELSE 0 END) AS n_pdf,
               SUM(CASE WHEN d.extraction_method='web_fetch' THEN 1 ELSE 0 END) AS n_web,
               SUM(CASE WHEN d.extraction_method='template_estimate' THEN 1 ELSE 0 END) AS n_tmpl,
               SUM(CASE WHEN d.extraction_method='inferred' THEN 1 ELSE 0 END) AS n_inf,
               SUM(CASE WHEN d.extraction_method='unknown' THEN 1 ELSE 0 END) AS n_unk,
               COUNT(d.id) AS n_total
        FROM industry i LEFT JOIN industry_data_point d ON d.industry_id=i.id
        GROUP BY i.id, i.name, i.tier, i.status
        HAVING n_total > 0
        ORDER BY i.tier ASC, i.name ASC
    """):
        em_by_industry.append(dict(r))

    # ── Phase3 第五道防线:3 个新模块 ──
    # 模块 1:网搜源可信度分布
    cred_dist = {"whitelisted": 0, "unverified": 0, "blacklisted": 0}
    for r in query_all("SELECT source_credibility, COUNT(*) c FROM source GROUP BY source_credibility"):
        key = r["source_credibility"] or "unverified"
        cred_dist[key] = cred_dist.get(key, 0) + r["c"]
    cred_total = sum(cred_dist.values())

    # 模块 2:数据新鲜度仪表盘(按行业,基准 COALESCE(last_verified_at, created_at))
    fresh_by_industry: Dict[int, Dict[str, Any]] = {}
    for r in query_all("""
        SELECT i.id AS iid, i.name AS iname, i.tier, i.status,
               dp.last_verified_at AS lva, dp.created_at AS ca
        FROM industry i JOIN industry_data_point dp ON dp.industry_id = i.id
    """):
        slot = fresh_by_industry.setdefault(r["iid"], {
            "id": r["iid"], "name": r["iname"], "tier": r["tier"], "status": r["status"],
            "green": 0, "yellow": 0, "orange": 0, "red": 0, "gray": 0, "total": 0,
        })
        col = freshness(r["lva"], r["ca"], False)["color"]
        slot[col] += 1
        slot["total"] += 1
    fresh_dash = sorted(fresh_by_industry.values(),
                        key=lambda x: (x["tier"], x["name"]))

    # 模块 3:灰名单待 review 队列
    gray_queue = query_all("""
        SELECT * FROM source_review_queue
        WHERE user_decision IS NULL
        ORDER BY encountered_at DESC
    """)

    return render_template("audit_extraction.html",
                           rows=rows, grouped=grouped, totals=totals,
                           em_overall=em_overall, em_by_industry=em_by_industry,
                           cred_dist=cred_dist, cred_total=cred_total,
                           fresh_dash=fresh_dash, gray_queue=gray_queue)


# ── 路由:metric 详情页 /metric/<id>/<metric>/<as_of>/<fc>(任务 2e)──
@app.route("/metric/<int:industry_id>/<path:metric>/<as_of>/<int:is_forecast>")
def metric_detail(industry_id: int, metric: str, as_of: str, is_forecast: int):
    """展示某 peer group 完整对照 + 共识状态。"""
    ind = query_one("SELECT * FROM industry WHERE id=?", (industry_id,))
    if not ind:
        abort(404, f"industry id={industry_id} 不存在")

    peer = query_one("""
        SELECT * FROM data_point_peer_group
        WHERE industry_id=? AND metric=? AND as_of_date=? AND is_forecast=?
          AND company_id IS NULL
    """, (industry_id, metric, as_of, is_forecast))

    dps = query_all("""
        SELECT dp.*,
               s.title AS source_title, s.quality_tier AS source_tier,
               s.publisher AS source_publisher, s.source_type AS source_type
        FROM industry_data_point dp
        LEFT JOIN source s ON s.id = dp.source_id
        WHERE dp.industry_id=? AND dp.metric=?
          AND (COALESCE(NULLIF(dp.as_of_date, ''), dp.period) = ?)
          AND dp.is_forecast=?
        ORDER BY dp.consensus_status, dp.deviation_from_median
    """, (industry_id, metric, as_of, is_forecast))

    return render_template(
        "metric_detail.html",
        ind=ind, metric=metric, as_of=as_of, is_forecast=is_forecast,
        peer=peer, data_points=dps,
    )


# ── 路由:公司透视页(Phase3 任务 3.1)────────────────
@app.route("/industry/<int:industry_id>/companies")
def industry_companies(industry_id: int):
    """公司透视页(嵌行业内,因同公司不同行业 profile 不同)。
    三张表(全球/中国/技术派)+ 画像卡片瀑布流。
    Stage 1:company_profile 为空 → 正常 fallback 显示"待回填"。
    """
    ind = query_one("SELECT * FROM industry WHERE id=?", (industry_id,))
    if not ind:
        abort(404, f"industry id={industry_id} 不存在")
    is_pcb_equipment = ind.get("name") == "PCB专用设备"

    profiles = query_all("""
        WITH latest_profile AS (
          SELECT cp.*
          FROM company_profile cp
          JOIN (
            SELECT company_id, industry_id, MAX(id) AS max_id
            FROM company_profile
            GROUP BY company_id, industry_id
          ) x ON x.max_id = cp.id
        )
        SELECT ci.company_id, ci.industry_id, cp.id AS profile_id, cp.*,
               c.name AS company_name, c.ticker, c.market,
               c.listing_status AS c_listing_status, c.display_mode,
               c.note AS company_note, c.created_at AS company_created_at,
               c.brief_intro AS company_brief_intro,
               c.brief_intro_src AS company_brief_intro_src,
               c.pe_ttm, c.pe_forward, c.pb, c.roe, c.roa, c.eps_ttm, c.bps_mrq,
               c.per_share_currency, c.financial_metrics_as_of, c.financial_metrics_source_id,
               c.market_cap_value, c.market_cap_unit,
               c.market_cap_cny, c.market_cap_usd, c.valuation_as_of,
               c.valuation_source_id
        FROM company_industry ci
        JOIN company c ON c.id = ci.company_id
        LEFT JOIN latest_profile cp
          ON cp.company_id = ci.company_id AND cp.industry_id = ci.industry_id
        WHERE ci.industry_id=?
        ORDER BY cp.global_rank IS NULL, cp.global_rank ASC,
                 cp.china_rank IS NULL, cp.china_rank ASC,
                 c.name ASC
    """, (industry_id,))

    # 公司透视是 research.db 的行业画像与 financial.db 的结构化财务只读组合。
    # 供应商快照不得回写旧 company/company_profile 聚合列；这里只在内存中按
    # 规范 company_id + ticker 双重校验后补齐展示。
    financial_bundles = _overlay_industry_financial_rows(
        profiles, include_profile_series=True,
    )

    # 解析 JSON 字段 + 计算新鲜度
    for p in profiles:
        profile_created_at            = p.get("created_at")
        p["has_profile"]             = p.get("profile_id") is not None
        p["revenue_series_list"]    = _json_or([], p.get("revenue_series"))
        p["net_income_series_list"] = _json_or([], p.get("net_income_series"))
        p["recent_events_list"]     = _json_or([], p.get("recent_events"))
        if is_pcb_equipment:
            p["recent_events_list"] = _pcb_public_recent_events(p["recent_events_list"])
        p["risks_list"]             = _json_or([], p.get("risks"))
        _sids                       = _json_or([], p.get("source_ids"))
        p["source_ids_list"]        = _sids if isinstance(_sids, list) else ([_sids] if _sids not in (None, "") else [])
        p["listing_status"]         = p.get("c_listing_status") or p.get("listing_status")
        # company_industry 是完整公司集合；company_profile 只是行业画像增强层。
        # 尚无 profile 时保留公司级简介/建档日期作为页面 fallback，但绝不
        # 给 in_global_table/in_china_table/is_china_tech_leader 等精选标记造默认值。
        p["summary"]                = p.get("summary") or p.get("company_brief_intro") or p.get("company_note")
        p["brief_intro"]            = p.get("brief_intro") or p.get("company_brief_intro")
        p["brief_intro_src"]        = p.get("brief_intro_src") or p.get("company_brief_intro_src")
        p["created_at"]             = profile_created_at or p.get("company_created_at")
        p["is_unlisted"]            = (
            p["listing_status"] in UNLISTED_LISTING_STATUSES
            or (is_pcb_equipment and not p.get("ticker"))
        )
        # 公司建档日不是行业画像或估值的验证日。缺少画像/估值证据时必须
        # 显示“未知”，不能用 company.created_at 伪造数据新鲜度。
        p["fresh_general"]          = (
            freshness(
                p.get("financials_as_of") or p.get("last_verified_at"),
                profile_created_at,
                False,
            )
            if p["has_profile"] else freshness()
        )
        p["fresh_valuation"]        = freshness(p.get("valuation_as_of"), None, True)
        p["financial_rows"] = _aligned_company_financial_rows(
            p["revenue_series_list"], p["net_income_series_list"]
        )
        p["public_coverage_note"] = (
            _pcb_public_coverage_note(p) if is_pcb_equipment else None
        )
        p["financial_absence_label"] = (
            "无独立上市财务"
            if is_pcb_equipment and p["is_unlisted"]
            else (
                "当前结构化财务源未返回可展示损益序列"
                if financial_bundles.get(int(p["company_id"]))
                else "尚未建立结构化财务画像"
            )
        )
        p["core_metrics"] = _company_metric_cards(
            p,
            p,
            strict_financial_source=is_pcb_equipment,
            financial_bundle=financial_bundles.get(int(p["company_id"])),
        )
        if is_pcb_equipment:
            p["display_note"] = _pcb_public_profile_note(p.get("display_note"))
        pe_card = next(card for card in p["core_metrics"] if card["key"] == "pe_ttm")
        p["pe_ttm_display"] = pe_card["display"] or pe_card["reason"]

    global_tbl = [p for p in profiles if p.get("in_global_table")]
    china_tbl  = [p for p in profiles if p.get("in_china_table")]
    tech_tbl   = [p for p in profiles if p.get("is_china_tech_leader")]

    # 新鲜度概览(三色计数)— 基于 profile 的常规新鲜度
    fresh_counts = {"green": 0, "yellow": 0, "orange": 0, "red": 0, "gray": 0}
    for p in profiles:
        fresh_counts[p["fresh_general"]["color"]] += 1

    last_refresh = None
    if profiles:
        vals = [p.get("last_verified_at") or p.get("last_updated") for p in profiles if (p.get("last_verified_at") or p.get("last_updated"))]
        last_refresh = max(vals) if vals else None

    # 2c-E:子市场份额真分表(company_sub_market_share)— 按 (geo, sub_market) 分组,每组独立 section
    sms_rows = query_all("""
        SELECT s.*, c.name AS company_name, c.ticker
        FROM company_sub_market_share s JOIN company c ON c.id = s.company_id
        WHERE s.industry_id = ?
        ORDER BY s.geo, s.sub_market, (s.rank IS NULL), s.rank ASC, s.share DESC
    """, (industry_id,))
    _sm = {}
    for r in sms_rows:
        _sids = _json_or([], r.get("source_ids"))
        r["source_ids_list"] = _sids if isinstance(_sids, list) else ([_sids] if _sids not in (None, "") else [])
        key = (r["geo"], r["sub_market"])
        g = _sm.setdefault(key, {"geo": r["geo"], "sub_market": r["sub_market"],
                                 "rows": [], "total": 0.0, "has_unverified": False})
        g["rows"].append(r)
        if r.get("share") is not None:
            g["total"] += r["share"]
        if r.get("credibility") == "unverified":
            g["has_unverified"] = True
    for g in _sm.values():
        g["total"] = round(g["total"], 1)
        g["sum_ok"] = (80.0 <= g["total"] <= 110.0)
    sub_market_groups = sorted(_sm.values(), key=lambda g: (g["geo"] != "global", g["sub_market"]))
    missing_gross_margin_names = [
        str(p["company_name"])
        for p in profiles
        if p.get("gross_margin") is None and p.get("net_margin") is not None
    ]
    landscape_figures = _company_landscape_figures(profiles)
    # 行业级公司透视正文与结构化公司卡片承担不同职责：Markdown 保存
    # 跨主体竞争、经营和估值分析，卡片读取 research/financial 两库的
    # 当前结构化数据。过去只生成前者却没有接入页面，造成“文件存在但
    # 用户看不到”。文件不存在时保持原有通用页面兼容。
    company_report = load_md(
        DOCS_DIR / "industries" / f"{ind['name']}_公司透视.md"
    )
    if company_report.get("exists"):
        company_report["html"] = wrap_markdown_tables_for_scroll(
            str(company_report["html"])
        )

    return render_template(
        "industry_companies.html",
        ind=ind,
        q_dimensions=industry_q_dimensions(ind["name"]),
        profiles=profiles,
        global_tbl=global_tbl,
        china_tbl=china_tbl,
        tech_tbl=tech_tbl,
        fresh_counts=fresh_counts,
        last_refresh=last_refresh,
        sub_market_groups=sub_market_groups,
        missing_gross_margin_names=missing_gross_margin_names,
        landscape_figures_json=json.dumps(landscape_figures),
        is_pcb_equipment=is_pcb_equipment,
        company_report=company_report,
    )


# ── 路由:估值对比独立模块(Stage 2c-F 任务 C,梁总点名)────
# 与公司透视拆开:公司透视=业务相关,估值对比=财务相关。
# 两视图:按指标看(每指标一张降序排行)/ 按公司看(每家一张卡片)。
# 每个数字 cell 级 ^src(yfinance 估值→valuation_source_id;盈利预测→forecast_source_id;
# 毛/净利率走 yfinance 同源;一级市场估值→company_profile.source_ids)。
VALUATION_METRICS = [
    # key,             label,           source,    pct?,  higher_better(用于"高/低"提示,非排序方向)
    ("pe_ttm",          "PE (TTM)",       "val",     False),
    ("pe_forward",      "PE (Forward)",   "val",     False),
    ("pb",              "PB",             "val",     False),
    ("ps_ttm",          "PS (TTM)",       "val",     False),
    ("ev_ebitda",       "EV / EBITDA",    "val",     False),
    ("peg",             "PEG",            "val",     False),
    ("roe",             "ROE",            "fin",     True),
    ("roa",             "ROA",            "fin",     True),
    ("eps_ttm",         "EPS (TTM)",      "fin",     True),
    ("bps_mrq",         "BPS (MRQ)",      "fin",     True),
    ("gross_margin",    "毛利率",          "fin",     True),
    ("net_margin",      "净利率",          "fin",     True),
    ("market_cap_cny",  "市值（亿元人民币）", "val",     True),   #  统一人民币口径，页面括号补美元等值
]

VALUATION_FORMULAS = {
    "pe_ttm": "市盈率 = 股价 / 过去 12 个月每股收益",
    "pe_forward": "远期市盈率 = 股价 / 未来 12 个月预期每股收益",
    "pb": "市净率 = 股价 / 每股净资产",
    "ps_ttm": "市销率 = 总市值 / 过去 12 个月营业收入",
    "ev_ebitda": "企业价值倍数 = 企业价值 / EBITDA",
    "peg": "PEG = 市盈率 / 预期盈利增长率",
    "roe": "净资产收益率 = 归母净利润 / 平均归母净资产",
    "roa": "总资产收益率 = 净利润 / 平均总资产",
    "eps_ttm": "每股收益 = 过去 12 个月归母净利润 / 加权平均普通股数",
    "bps_mrq": "每股净资产 = 期末归母股东权益 / 期末普通股数",
    "gross_margin": "毛利率 =（营业收入 − 营业成本）/ 营业收入",
    "net_margin": "净利率 = 归母净利润 / 营业收入",
    "market_cap_cny": "市值 = 股价 × 总股本（统一折算为亿元人民币）",
}
VALUATION_CORE_KEYS = ("pe_ttm", "pb", "roe", "roa", "eps_ttm", "bps_mrq")


def _overlay_industry_financial_rows(
    rows: list[dict[str, Any]],
    *,
    include_profile_series: bool = False,
) -> dict[int, dict[str, Any]]:
    """Use financial.db as the read-only authority for industry financial tables.

    The industry valuation page predates the separate financial database and still
    carries nullable legacy compatibility columns in research.db.  New market and
    financial observations must not be copied back into those columns, but a
    non-null legacy value must also never win over the authoritative financial
    observation.  This adapter replaces display fields in memory and preserves the
    provider/date for every field so all company and valuation pages resolve the
    same observation identity.
    """
    current_keys = (
        "pe_ttm", "pe_forward", "pb", "ps_ttm", "ev_ebitda",
        "roe", "roa", "eps_ttm", "bps_mrq",
        "market_cap_cny", "market_cap_usd",
    )
    for row in rows:
        row["_provider_by_metric"] = {}
        row["_source_title_by_metric"] = {}
        row["_as_of_by_metric"] = {}
    try:
        batch_bundles = financial_company_page_summaries_batch(
            [int(row["company_id"]) for row in rows],
            db_path=FINANCIAL_DB_PATH,
        )
    except Exception:
        log.exception("行业公司页批量读取 financial.db 失败")
        batch_bundles = {}

    bundles: dict[int, dict[str, Any]] = {}
    for row in rows:
        company_id = int(row["company_id"])
        bundle = batch_bundles.get(company_id)
        if not bundle:
            continue
        # 跨库链接必须同时通过规范证券身份复核。company_id 在测试夹具、
        # 迁移库或错误映射中可能碰巧相同，不能仅凭整数主键把另一只证券
        # 的财务数据覆盖到当前行。
        security = bundle.get("security") or {}
        row_ticker = str(row.get("ticker") or "").strip().upper()
        financial_ticker = str(security.get("ticker") or "").strip().upper()
        if not row_ticker or not financial_ticker or row_ticker != financial_ticker:
            continue
        bundles[company_id] = bundle
        row["_financial_authority_applied"] = True
        row["financials_as_of"] = None
        row["ocf_unit"] = None
        row["per_share_currency"] = None
        # financial_data has no canonical PEG observation yet.  Suppress the
        # legacy aggregate rather than presenting it beside authoritative rows.
        row["peg"] = None
        if include_profile_series:
            row["revenue_series"] = "[]"
            row["net_income_series"] = "[]"
        current = bundle.get("current_metrics") or {}
        for key in current_keys:
            # A missing/not-applicable authoritative observation suppresses any
            # stale compatibility aggregate; otherwise delisted or loss-making
            # securities can silently resurrect old PE/PB values.
            row[key] = None
            observation = current.get(key)
            if not observation or observation.get("value_num") is None:
                continue
            row[key] = observation["value_num"]
            row["_provider_by_metric"][key] = observation.get("provider_label")
            row["_source_title_by_metric"][key] = observation.get("source_title")
            row["_as_of_by_metric"][key] = observation.get("as_of_date")

        # 毛利率和净利率是报表期指标，取最新完整历史期；不拿市场日快照
        # 冒充报表值。
        historical = bundle.get("historical_table") or []
        for key in ("gross_margin", "net_margin", "operating_cash_flow"):
            row[key] = None
        if historical:
            for key in ("gross_margin", "net_margin", "operating_cash_flow"):
                selected_observation = next(
                    (
                        (period_row, candidate)
                        for period_row in reversed(historical)
                        if (
                            candidate := (period_row.get("metrics") or {}).get(key)
                        )
                        and candidate.get("value") is not None
                    ),
                    None,
                )
                if not selected_observation:
                    continue
                period_row, observation = selected_observation
                if not observation or observation.get("value") is None:
                    continue
                row[key] = observation["value"]
                if key == "operating_cash_flow":
                    row["ocf_unit"] = observation.get("unit")
                provider = str(observation.get("provider") or "")
                row["_provider_by_metric"][key] = {
                    "wind": "Wind",
                    "tushare": "Tushare",
                    "yfinance": "yfinance",
                    "company_filing": "公司披露",
                }.get(provider.lower(), provider)
                row["_source_title_by_metric"][key] = observation.get("source_title")
                period_label = str(
                    period_row.get("period_end")
                    or period_row.get("period")
                    or observation.get("as_of_date")
                    or ""
                )
                if len(period_label) == 4 and period_label.isdigit():
                    period_label = f"{period_label}-12-31"
                row["_as_of_by_metric"][key] = period_label or observation.get("as_of_date")
            historical_dates = [
                str(obs.get("as_of_date"))
                for period_row in historical
                for obs in (period_row.get("metrics") or {}).values()
                if obs and obs.get("as_of_date")
            ]
            if historical_dates:
                row["financials_as_of"] = max(historical_dates)

            if include_profile_series:
                revenue_series: list[dict[str, Any]] = []
                net_income_series: list[dict[str, Any]] = []
                previous_revenue: Optional[float] = None
                previous_revenue_unit: Optional[str] = None
                previous_net_income: Optional[float] = None
                previous_net_income_unit: Optional[str] = None
                for period_row in historical[-5:]:
                    period = str(period_row.get("period") or "").strip()
                    metrics = period_row.get("metrics") or {}
                    revenue = metrics.get("revenue") or {}
                    net_income = metrics.get("net_income") or {}
                    revenue_value = revenue.get("value")
                    revenue_unit = revenue.get("unit")
                    if period and revenue_value is not None:
                        revenue_yoy = None
                        if (
                            previous_revenue not in (None, 0)
                            and previous_revenue_unit == revenue_unit
                        ):
                            revenue_yoy = (
                                (float(revenue_value) / float(previous_revenue) - 1)
                                * 100
                            )
                        revenue_series.append({
                            "period": period,
                            "value": round(float(revenue_value), 2),
                            "unit": revenue_unit,
                            "yoy": (
                                round(revenue_yoy, 1)
                                if revenue_yoy is not None else None
                            ),
                            "provider": revenue.get("provider"),
                            "source_title": revenue.get("source_title"),
                        })
                        previous_revenue = float(revenue_value)
                        previous_revenue_unit = revenue_unit
                    net_income_value = net_income.get("value")
                    net_income_unit = net_income.get("unit")
                    if period and net_income_value is not None:
                        net_income_yoy = None
                        if (
                            previous_net_income not in (None, 0)
                            and previous_net_income_unit == net_income_unit
                        ):
                            net_income_yoy = (
                                (
                                    float(net_income_value)
                                    / float(previous_net_income)
                                    - 1
                                )
                                * 100
                            )
                        net_income_series.append({
                            "period": period,
                            "value": round(float(net_income_value), 2),
                            "unit": net_income_unit,
                            "yoy": (
                                round(net_income_yoy, 1)
                                if net_income_yoy is not None else None
                            ),
                            "provider": net_income.get("provider"),
                            "source_title": net_income.get("source_title"),
                        })
                        previous_net_income = float(net_income_value)
                        previous_net_income_unit = net_income_unit
                if revenue_series:
                    row["revenue_series"] = json.dumps(
                        revenue_series, ensure_ascii=False,
                    )
                if net_income_series:
                    row["net_income_series"] = json.dumps(
                        net_income_series, ensure_ascii=False,
                    )

        # 行业兼容页只展示一致预期，不把内部模型混入“盈利预测一致预期”。
        forecasts = {
            str(item.get("horizon")): item.get("consensus") or {}
            for item in (bundle.get("forecast_table") or [])
        }
        for field in (
            "forecast_revenue_year1", "forecast_revenue_year2",
            "forecast_eps_year1", "forecast_eps_year2",
        ):
            row[field] = None
        row["forecast_revenue_unit"] = None
        row["forecast_as_of_date"] = None
        for horizon, suffix in (("FY1", "year1"), ("FY2", "year2")):
            forecast = forecasts.get(horizon) or {}
            revenue = forecast.get("revenue")
            eps = forecast.get("eps")
            if revenue:
                row[f"forecast_revenue_{suffix}"] = revenue.get("value")
                row["forecast_revenue_unit"] = revenue.get("unit")
            if eps:
                row[f"forecast_eps_{suffix}"] = eps.get("value")
            representative = revenue or eps
            if representative:
                row["_forecast_provider"] = {
                    "wind": "Wind 一致预期",
                    "tushare": "Tushare 一致预期",
                    "external_consensus": "最近两个季度卖方预测中位数",
                }.get(
                    str(representative.get("provider") or "").lower(),
                    str(representative.get("provider") or "一致预期"),
                )
                row["_forecast_source_title"] = representative.get("source_title")
                row["forecast_as_of_date"] = representative.get("as_of_date")

        if row.get("per_share_currency") is None:
            row["per_share_currency"] = _per_share_currency_from_unit(
                (current.get("eps_ttm") or {}).get("unit")
                or (current.get("bps_mrq") or {}).get("unit")
            )
        valuation_dates = [
            str(row["_as_of_by_metric"][key])
            for key in ("pe_ttm", "pe_forward", "pb", "ps_ttm", "ev_ebitda", "market_cap_cny", "market_cap_usd")
            if row["_as_of_by_metric"].get(key)
        ]
        financial_dates = [
            str(row["_as_of_by_metric"][key])
            for key in ("roe", "roa", "eps_ttm", "bps_mrq")
            if row["_as_of_by_metric"].get(key)
        ]
        row["valuation_as_of"] = max(valuation_dates) if valuation_dates else None
        row["financial_metrics_as_of"] = (
            max(financial_dates) if financial_dates else None
        )
    return bundles


def _fmt_metric(key, val):
    if val is None:
        return None
    try:
        f = float(val)
    except Exception:
        return str(val)
    if key in ("roe", "roa", "gross_margin", "net_margin"):
        return f"{f:.2f}%"
    if key in ("pe_ttm", "pe_forward", "pb", "ps_ttm", "ev_ebitda", "peg"):
        return f"{f:.2f}×"
    if key in ("market_cap_cny", "market_cap_value"):
        return f"{f:,.2f}"
    return f"{f:.2f}"


def _valuation_scatter(
    rows: list,
    xkey: str,
    xlabel: str,
    *,
    ykey: str = "roe",
    ylabel: str = "ROE (%)",
) -> Optional[dict]:
    """估值倍数与资产回报矩阵；中位线只作定位，不给出推荐。"""
    valid = []
    for row in rows:
        try:
            x, y = float(row.get(xkey)), float(row.get(ykey))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(x) and math.isfinite(y)) or x <= 0:
            continue
        valid.append((row, x, y))
    if len(valid) < 2:
        return None
    xs = [x for _, x, _ in valid]; ys = [y for _, _, y in valid]
    xmed = median(xs); ymed = median(ys)
    caps = [max(float((r.get("market_cap_cny") or 0)), 0) for r, _, _ in valid]
    positive_caps = [c for c in caps if c > 0]
    cap_ref = max(positive_caps) if positive_caps else 1
    grouped = {}
    for (row, x, y), cap in zip(valid, caps):
        group = row.get("valuation_group_label") or row.get("market") or "其他市场"
        grouped.setdefault(group, []).append((row, x, y, cap))
    data = []
    for idx, (group, items) in enumerate(sorted(grouped.items())):
        first_row = items[0][0]
        data.append({
            "type": "scatter", "mode": "markers+text", "name": group,
            "x": [x for _, x, _, _ in items], "y": [y for _, _, y, _ in items],
            "text": [r.get("company_name") for r, _, _, _ in items],
            "textposition": "top center",
            "textfont": {"size": 10, "color": "#41566d"},
            "cliponaxis": False,
            "customdata": [[r.get("ticker") or "—", cap, r.get("valuation_as_of") or "—"]
                           for r, _, _, cap in items],
            "marker": {"size": [max(9, min(36, 9 + 27 * math.sqrt(cap / cap_ref))) if cap else 9
                                 for _, _, _, cap in items],
                       "color": first_row.get("valuation_color")
                                or FUNDA_COLORWAY[idx % len(FUNDA_COLORWAY)],
                       "symbol": first_row.get("valuation_symbol") or "circle",
                       "opacity": .80,
                       "line": {"color": "#ffffff", "width": 1}},
            "hovertemplate": (
                "%{text}<br>代码 %{customdata[0]}<br>"
                + xlabel
                + " %{x:.2f}<br>"
                + ylabel
                + " %{y:.2f}<br>市值 %{customdata[1]:,.2f} 亿元"
                "<br>时点 %{customdata[2]}<extra></extra>"
            ),
        })
    base_trace_count = len(data)

    # 极端 ROE（例如重组后小净资产导致的四位数百分比）会把常规公司压成
    # 一条线。默认使用稳健范围，但原始点仍保留在市场 trace 中；超界公司
    # 另以贴边空心三角明确标识，并可一键切回完整原始范围。
    high_outliers, low_outliers = [], []
    robust_range = full_range = None
    if len(ys) >= 5:
        q1, _, q3 = quantiles(ys, n=4, method="inclusive")
        mad = median(abs(y - ymed) for y in ys)
        robust_scale = max((q3 - q1) / 1.349, mad * 1.4826, abs(ymed) * .1, 5.0)
        lower_fence, upper_fence = ymed - 4 * robust_scale, ymed + 4 * robust_scale
        low_outliers = [(row, x, y) for row, x, y in valid if y < lower_fence]
        high_outliers = [(row, x, y) for row, x, y in valid if y > upper_fence]
        inlier_ys = [y for _, _, y in valid if lower_fence <= y <= upper_fence]
        if inlier_ys and (low_outliers or high_outliers):
            inlier_span = max(inlier_ys) - min(inlier_ys)
            robust_pad = max(inlier_span * .08, 1.0)
            robust_range = [min(inlier_ys) - robust_pad, max(inlier_ys) + robust_pad]
            full_span = max(ys) - min(ys)
            full_pad = max(full_span * .05, 1.0)
            full_range = [min(ys) - full_pad, max(ys) + full_pad]

            for direction, outliers, boundary, symbol, color in (
                ("高", high_outliers, robust_range[1] - robust_pad * .25,
                 "triangle-up-open", "#b45309"),
                ("低", low_outliers, robust_range[0] + robust_pad * .25,
                 "triangle-down-open", "#b45309"),
            ):
                if not outliers:
                    continue
                data.append({
                    "type": "scatter", "mode": "markers",
                    "name": f"默认范围外（{direction}）", "showlegend": False,
                    "x": [x for _, x, _ in outliers],
                    "y": [boundary] * len(outliers),
                    "text": [row.get("company_name") for row, _, _ in outliers],
                    "customdata": [[row.get("ticker") or "—", y]
                                   for row, _, y in outliers],
                    "marker": {"size": 13, "symbol": symbol, "color": color,
                               "line": {"color": color, "width": 2}},
                    "hovertemplate": "%{text}<br>代码 %{customdata[0]}<br>"
                                     f"原始 {ylabel} %{{customdata[1]:.2f}}<br>"
                                     "默认稳健范围外；可切换完整范围<extra></extra>",
                })

    layout = {
        "height": 410, "margin": {"l": 62, "r": 20, "t": 24, "b": 56},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "#fbfdff",
        "hovermode": "closest", "legend": {"orientation": "h", "x": 0, "y": 1.12},
        "xaxis": {"title": xlabel, "gridcolor": "#e8edf5", "zeroline": False},
        "yaxis": {"title": ylabel, "gridcolor": "#e8edf5", "zerolinecolor": "#cbd5e1"},
        "shapes": [
            {"type": "line", "xref": "x", "yref": "paper", "x0": xmed, "x1": xmed, "y0": 0, "y1": 1,
             "line": {"color": "#94a3b8", "dash": "dot"}},
            {"type": "line", "xref": "paper", "yref": "y", "x0": 0, "x1": 1, "y0": ymed, "y1": ymed,
             "line": {"color": "#94a3b8", "dash": "dot"}},
        ],
        "annotations": [{"xref": "paper", "yref": "paper", "x": 1, "y": 1.02, "showarrow": False,
                         "text": f"同行中位数：{xlabel} {xmed:.2f} / {ylabel} {ymed:.2f}",
                         "font": {"size": 10, "color": "#64748b"}}],
    }
    if robust_range is not None and full_range is not None:
        overflow_trace_count = len(data) - base_trace_count
        layout["yaxis"]["range"] = robust_range
        layout["annotations"].append({
            "xref": "paper", "yref": "paper", "x": 0, "y": 1.02,
            "xanchor": "left", "showarrow": False,
            "text": (f"▲ 默认范围外 {len(high_outliers) + len(low_outliers)} 家贴边显示；"
                     "悬浮看原值 / 可切换完整范围"),
            "font": {"size": 10, "color": "#b45309"},
        })
        layout["updatemenus"] = [{
            "type": "buttons", "direction": "right", "active": 0,
            "x": 0, "y": 1.16, "xanchor": "left", "yanchor": "top",
            "buttons": [
                {"label": "稳健范围", "method": "update", "args": [
                    {"visible": [True] * (base_trace_count + overflow_trace_count)},
                    {"yaxis.range": robust_range},
                ]},
                {"label": "完整范围", "method": "update", "args": [
                    {"visible": [True] * base_trace_count + [False] * overflow_trace_count},
                    {"yaxis.range": full_range},
                ]},
            ],
        }]
    return {"data": data, "layout": layout}


PCB_VALUATION_HEATMAP_COLORSCALE = [
    [0, "#fff1f2"],
    [.5, "#fca5a5"],
    [1, "#ef4444"],
]


def _valuation_heatmap(
    rows: list,
    specs: tuple[tuple[str, str], ...] | None = None,
    colorscale: list[list[Any]] | None = None,
) -> Optional[dict]:
    """Selected comparable metrics as a peer-percentile heatmap.

    ``specs`` is explicit so a research package can exclude profitability
    ratios when providers, fiscal years or accounting standards are not
    comparable. EPS/BPS remain in exact tables because currencies differ.
    """
    specs = specs or (("pe_ttm", "PE"), ("pb", "PB"), ("roe", "ROE"), ("roa", "ROA"))
    def comparable_value(row: dict, key: str) -> Optional[float]:
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or (key in ("pe_ttm", "pb", "ps_ttm", "ev_ebitda") and value <= 0):
            return None
        return value

    # 展示 eligibility 要求至少两项可比；36 家仅是渲染上限。单列分位的
    # peer pool 则应纳入原始同行中该列所有有效值（即使该同行只有这一项），
    # 不能把展示门槛或页面截断误当成统计总体。
    eligible = [
        row for row in rows
        if sum(comparable_value(row, key) is not None for key, _ in specs) >= 2
    ]
    eligible.sort(key=lambda r: (
        r.get("market_cap_cny") is None,
        -(r.get("market_cap_cny") or 0),
        r.get("company_name") or "",
    ))
    selected = eligible[:36]
    if len(eligible) < 2 or len(selected) < 2:
        return None
    columns, raw_columns = [], []
    for key, _ in specs:
        values = [comparable_value(row, key) for row in selected]
        present = sorted(
            value for row in rows
            if (value := comparable_value(row, key)) is not None
        )
        denom = max(len(present) - 1, 1)
        percentiles = []
        for value in values:
            if value is None:
                percentiles.append(None)
                continue
            # 相同原值取并列名次的平均分位，避免 ties 全部落在最低名次。
            left = bisect_left(present, value)
            right = bisect_right(present, value) - 1
            percentiles.append(100 * ((left + right) / 2) / denom)
        columns.append(percentiles); raw_columns.append(values)
    z = [[columns[j][i] for j in range(len(specs))] for i in range(len(selected))]
    text_values = [[("—" if raw_columns[j][i] is None else f"{raw_columns[j][i]:.2f}")
                    for j in range(len(specs))] for i in range(len(selected))]
    heatmap_labels = [
        str(r.get("heatmap_label") or r.get("company_name") or "")
        for r in selected
    ]
    max_label_chars = max((len(label) for label in heatmap_labels), default=0)
    left_margin = max(120, min(220, max_label_chars * 12 + 24))
    return {"data": [{
        "type": "heatmap", "z": z, "x": [label for _, label in specs],
        "y": heatmap_labels,
        "text": text_values,
        "texttemplate": "%{text}", "textfont": {"size": 10},
        "colorscale": colorscale or [[0, "#e8f3fb"], [.5, "#7ab5d8"], [1, "#164e78"]],
        "colorbar": {"title": "同行数值分位", "ticksuffix": "%"},
        "hovertemplate": "%{y}<br>%{x} 原值 %{text}<br>同行数值分位 %{z:.0f}%<extra></extra>",
    }], "layout": {
        "height": max(360, 34 * len(selected) + 100),
        "margin": {"l": left_margin, "r": 70, "t": 24, "b": 46},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "#fbfdff",
        "xaxis": {"side": "top"},
        "yaxis": {"autorange": "reversed", "automargin": True},
    }}


@app.route("/industry/<int:industry_id>/valuation")
def industry_valuation(industry_id: int):
    """估值对比页(梁总点名)。按指标 / 按公司 两视图,cell 级 ^src。"""
    ind = query_one("SELECT * FROM industry WHERE id=?", (industry_id,))
    if not ind:
        abort(404, f"industry id={industry_id} 不存在")
    is_pcb_equipment = ind.get("name") == "PCB专用设备"
    is_copper = ind.get("name") == "铜"

    rows = query_all("""
        WITH latest_profile AS (
          SELECT cp.* FROM company_profile cp
          JOIN (
            SELECT company_id, industry_id, MAX(id) AS max_id
            FROM company_profile GROUP BY company_id, industry_id
          ) x ON x.max_id=cp.id
        )
        SELECT ci.company_id, ci.industry_id, ci.role AS industry_role,
               ci.note AS industry_relation_note,
               cp.gross_margin, cp.net_margin, cp.display_note,
               cp.private_valuation_value, cp.private_valuation_unit,
               cp.private_round, cp.private_valuation_as_of, cp.source_ids AS profile_source_ids,
               cp.financials_as_of,
               c.name AS company_name, c.ticker, c.market, c.listing_status,
               c.pe_ttm, c.pe_forward, c.pb, c.ps_ttm, c.ev_ebitda, c.peg,
               c.roe, c.roa, c.eps_ttm, c.bps_mrq, c.per_share_currency,
               c.financial_metrics_as_of, c.financial_metrics_source_id,
               c.market_cap_value, c.market_cap_unit,
               c.market_cap_cny, c.market_cap_usd, c.valuation_as_of,
               c.forecast_eps_year1, c.forecast_eps_year2,
               c.forecast_revenue_year1, c.forecast_revenue_year2,
               c.forecast_revenue_unit, c.forecast_as_of_date,
               c.forecast_source_id, c.valuation_source_id
        FROM company_industry ci
        JOIN company c ON c.id = ci.company_id
        LEFT JOIN latest_profile cp
          ON cp.company_id=ci.company_id AND cp.industry_id=ci.industry_id
        WHERE ci.industry_id = ?
        ORDER BY c.market_cap_cny IS NULL, c.market_cap_cny DESC, c.name
    """, (industry_id,))

    _overlay_industry_financial_rows(rows)

    for p in rows:
        sids = _json_or([], p.get("profile_source_ids"))
        p["profile_source_ids_list"] = sids if isinstance(sids, list) else ([sids] if sids not in (None, "") else [])
        p["is_unlisted"] = (
            p.get("listing_status") in UNLISTED_LISTING_STATUSES
            or (is_pcb_equipment and not p.get("ticker"))
        )
        # cell ^src 选源
        p["_val_src"] = p.get("valuation_source_id")
        p["_fin_src"] = (
            p.get("financial_metrics_source_id")
            if is_pcb_equipment
            else p.get("financial_metrics_source_id") or p.get("valuation_source_id")
        )
        p["_fc_src"]  = p.get("forecast_source_id")
        p["_priv_src"] = (p["profile_source_ids_list"][0] if p["profile_source_ids_list"] else None)
        role = str(p.get("industry_role") or "")
        if is_pcb_equipment:
            p["display_note"] = _pcb_public_profile_note(p.get("display_note"))
            name = str(p.get("company_name") or "")
            region_group = "中国大陆" if p.get("market") == "A股" else "海外"
            if any(term in role for term in ("曝光", "成像", "LDI", "DI")):
                track = "曝光与直接成像"
            elif any(term in role for term in ("VCP", "湿制程", "电镀", "化学品")):
                track = "电镀与湿制程"
            elif any(term in role for term in ("钻孔", "成型")):
                track = "钻孔与成型"
            elif any(term in role for term in ("检测", "电测", "测试", "AOI", "机器视觉")):
                track = "检测与电测"
            elif any(term in role for term in ("激光", "微加工")):
                track = "激光与微加工"
            elif any(term in role for term in ("热制程", "自动化", "综合设备")):
                track = "综合设备与自动化"
            else:
                track = "集团财务参照" if "母公司" in role or "集团" in role else role or "其他相关设备"
            p["valuation_region"] = region_group
            p["valuation_track"] = track
            p["is_direct_pcb_comparable"] = False
            if "当前排除" in role or "历史PCB业务" in role:
                p["comparison_group_label"] = "历史退出（不进入当前估值比较）"
                p["exclude_from_valuation"] = True
            elif not p.get("ticker"):
                p["comparison_group_label"] = "品牌、子公司或私营主体（无独立估值）"
                p["exclude_from_valuation"] = True
            elif "母公司财务参照" in role or "控股集团" in role:
                p["comparison_group_label"] = f"{region_group} · 集团财务参照"
                p["exclude_from_valuation"] = False
            elif "相邻" in role:
                p["comparison_group_label"] = f"{region_group} · {track}（相邻能力）"
                p["exclude_from_valuation"] = False
            else:
                p["comparison_group_label"] = f"{region_group} · {track}"
                p["exclude_from_valuation"] = False
                p["is_direct_pcb_comparable"] = True
        elif is_copper:
            ticker = str(p.get("ticker") or "").upper()
            role = str(p.get("industry_role") or "")
            if ticker in {"601899.SH", "603993.SH", "1208.HK"} or "资源矿山" in role:
                category = "资源矿山"
            elif "矿冶一体化" in role:
                category = "矿冶一体化"
            elif "铜加工材料" in role:
                category = "铜加工材料"
            else:
                category = "其他铜相关"
            is_hk = p.get("market") == "港股" or ticker.endswith(".HK")
            market_label = "港股" if is_hk else "A股"
            palette = {
                "资源矿山": {"A股": "#1d4ed8", "港股": "#7db4f3"},
                "矿冶一体化": {"A股": "#0f766e", "港股": "#67cdbd"},
                "铜加工材料": {"A股": "#c2410c", "港股": "#f2a56d"},
                "其他铜相关": {"A股": "#64748b", "港股": "#a8b3c2"},
            }
            p["valuation_track"] = category
            p["valuation_region"] = market_label
            p["valuation_group_label"] = f"{category} · {market_label}"
            p["comparison_group_label"] = p["valuation_group_label"]
            p["valuation_color"] = palette[category][market_label]
            p["valuation_symbol"] = "diamond" if is_hk else "circle"
            p["heatmap_label"] = f"{category}｜{p.get('company_name')}"
            p["exclude_from_valuation"] = False
        else:
            p["comparison_group_label"] = "行业关联公司"
            p["exclude_from_valuation"] = False

    valuation_rows = [p for p in rows if not p.get("exclude_from_valuation")]
    excluded_rows = [p for p in rows if p.get("exclude_from_valuation")]

    # ── 视图1:按指标看 ──
    metric_tables = []
    for key, label, src_kind, higher_better in VALUATION_METRICS:
        # 本专题的ROE/ROA和利润率来自跨市场、跨财年及不同数据商，保留在
        # 单公司卡片中，不制作会暗示可比性的全局排行榜。
        if is_pcb_equipment and key in {"roe", "roa", "gross_margin", "net_margin"}:
            continue
        items = []
        for p in valuation_rows:
            v = p.get(key)
            if v is None:
                continue
            if key == "pe_ttm" and not _positive_pe(v):
                continue
            disp = _fmt_metric(key, v)
            #  市值统一人民币口径,后接美元值
            if key == "market_cap_cny" and p.get("market_cap_usd") is not None:
                disp = f"{disp} 亿元人民币（约 {p['market_cap_usd']:,.2f} 亿美元）"
            elif key in ("eps_ttm", "bps_mrq") and p.get("per_share_currency"):
                disp = f"{disp} {p['per_share_currency']}/股"
            items.append({
                "company_id": p["company_id"], "name": p["company_name"],
                "ticker": p.get("ticker"), "listing_status": p.get("listing_status"),
                "raw": float(v), "display": disp,
                "comparison_group": (
                    (
                        f"{p['comparison_group_label']} · "
                        if is_pcb_equipment or is_copper
                        else ""
                    )
                    + ((str(p.get("per_share_currency")).strip().upper())
                       if p.get("per_share_currency")
                       else f"币种未标注·{p.get('market') or '市场未标注'}")
                    if key in ("eps_ttm", "bps_mrq")
                    else p["comparison_group_label"]
                ),
                "group_color": p.get("valuation_color"),
                "src_id": p["_fin_src"] if src_kind == "fin" else p["_val_src"],
                "source_text": (p.get("_provider_by_metric") or {}).get(key),
                "source_title": (p.get("_source_title_by_metric") or {}).get(key),
                "as_of": (
                    (p.get("_as_of_by_metric") or {}).get(key)
                    or p.get("financials_as_of")
                    if src_kind == "fin" and key in {"gross_margin", "net_margin"}
                    else (p.get("_as_of_by_metric") or {}).get(key)
                    or (p.get("financial_metrics_as_of") or p.get("financials_as_of"))
                    if src_kind == "fin"
                    else (p.get("_as_of_by_metric") or {}).get(key)
                    or p.get("valuation_as_of")
                ),
            })
        if is_copper and key in {"gross_margin", "net_margin"}:
            present_ids = {int(item["company_id"]) for item in items}
            for p in valuation_rows:
                if int(p["company_id"]) in present_ids:
                    continue
                items.append({
                    "company_id": p["company_id"],
                    "name": p["company_name"],
                    "ticker": p.get("ticker"),
                    "listing_status": p.get("listing_status"),
                    "raw": None,
                    "display": "公开口径不足，暂不排序",
                    "comparison_group": p["comparison_group_label"],
                    "group_color": p.get("valuation_color"),
                    "src_id": None,
                    "source_text": None,
                    "source_title": None,
                    "as_of": None,
                })
        if not items:
            continue
        is_per_share = key in ("eps_ttm", "bps_mrq")
        grouped_comparison = (
            is_per_share
            or is_pcb_equipment
            or (is_copper and key not in {"gross_margin", "net_margin"})
        )
        if grouped_comparison:
            # 每股数值只允许在同一明确币种内排序；币种缺失时按市场单列，并明确
            # 标为弱口径，绝不把 CNY/USD/HKD 原值混成一张全局排行榜。
            items.sort(
                key=lambda x: (
                    x["comparison_group"],
                    x["raw"] is None,
                    -(x["raw"] or 0),
                    x["name"],
                )
            )
            rank_by_group = {}
            for it in items:
                group = it["comparison_group"]
                if it["raw"] is None:
                    it["rank"] = "—"
                else:
                    rank_by_group[group] = rank_by_group.get(group, 0) + 1
                    it["rank"] = rank_by_group[group]
        else:
            items.sort(
                key=lambda x: (
                    x["raw"] is None,
                    -(x["raw"] or 0),
                    x["name"],
                )
            )
            for i, it in enumerate(items, 1):
                it["rank"] = i if it["raw"] is not None else "—"
        metric_tables.append({
            "key": key, "label": label, "rows": items,
            "formula": VALUATION_FORMULAS.get(key, ""),
            "grouped_per_share": is_per_share,
            "grouped_comparison": grouped_comparison,
        })

    # 估值横向对比图(Plotly · FUNDA 浅色风格):每个指标一张水平条形,>=2 家才画
    # 市值已统一为人民币亿元主口径，跨币种可比；美元亿元只作括号辅助展示。
    _NO_CHART_KEYS = set(VALUATION_CORE_KEYS) | {"gross_margin", "net_margin"}
    for mt in metric_tables:
        top = mt["rows"][:12]
        if len(top) >= 2 and mt["key"] not in _NO_CHART_KEYS and not is_pcb_equipment:
            mt["chart"] = _hbar_div(
                [it["name"] for it in top],
                [it["raw"] for it in top],
                [it["display"] for it in top],
            )
        else:
            mt["chart"] = ""

    # 盈利预测一致预期(独立表)
    forecast_rows = []
    for p in valuation_rows:
        if p.get("forecast_revenue_year1") is not None or p.get("forecast_eps_year1") is not None:
            forecast_rows.append({
                "company_id": p["company_id"], "name": p["company_name"], "ticker": p.get("ticker"),
                "rev1": p.get("forecast_revenue_year1"), "rev2": p.get("forecast_revenue_year2"),
                "eps1": p.get("forecast_eps_year1"), "eps2": p.get("forecast_eps_year2"),
                "unit": p.get("forecast_revenue_unit") or "",
                "as_of": p.get("forecast_as_of_date"), "src_id": p["_fc_src"],
                "source_text": p.get("_forecast_provider"),
                "source_title": p.get("_forecast_source_title"),
            })
    forecast_rows.sort(key=lambda x: (x["rev1"] is None, -(x["rev1"] or 0)))

    # 一级市场估值(未上市公司)
    private_rows = []
    for p in valuation_rows:
        if p["is_unlisted"] and p.get("private_valuation_value") is not None:
            private_rows.append({
                "company_id": p["company_id"], "name": p["company_name"],
                "value": p.get("private_valuation_value"), "unit": p.get("private_valuation_unit") or "",
                "round": p.get("private_round"), "as_of": p.get("private_valuation_as_of"),
                "src_id": p["_priv_src"],
            })

    # ── 视图2:按公司看 ──
    company_cards = []
    for p in valuation_rows:
        metrics = []
        for key, label, src_kind, higher_better in VALUATION_METRICS:
            v = p.get(key)
            display = _fmt_metric(key, v)
            has_value = v is not None
            if key == "pe_ttm" and v is None and p.get("net_margin") is not None and p.get("net_margin") < 0:
                display = "亏损/不可比"
                has_value = True
            if key == "market_cap_cny" and v is not None and p.get("market_cap_usd") is not None:
                display = f"{display} 亿元人民币（约 {p['market_cap_usd']:,.2f} 亿美元）"
            if key in ("eps_ttm", "bps_mrq") and v is not None and p.get("per_share_currency"):
                display = f"{display} {p['per_share_currency']}/股"
            if not has_value:
                if key == "bps_mrq" and "股本口径" in str(p.get("display_note") or ""):
                    display = "股本口径对账未通过，暂不展示"
                else:
                    display = "未上市 / 不适用" if p["is_unlisted"] or not p.get("ticker") else "接口不可得 / 待补抓"
            if key == "pe_ttm" and v is not None and not _positive_pe(v):
                display, has_value = "亏损/PE不适用", False
            metric_as_of = (
                (p.get("_as_of_by_metric") or {}).get(key)
                or p.get("financials_as_of")
                if src_kind == "fin" and key in {"gross_margin", "net_margin"}
                else (p.get("_as_of_by_metric") or {}).get(key)
                or (p.get("financial_metrics_as_of") or p.get("financials_as_of"))
                if src_kind == "fin"
                else (p.get("_as_of_by_metric") or {}).get(key)
                or p.get("valuation_as_of")
            )
            if not has_value:
                metric_as_of = None
            metrics.append({"key": key, "label": label, "display": display,
                            "formula": VALUATION_FORMULAS.get(key, ""),
                            "has": has_value,
                            "source_kind": src_kind,
                            "as_of": metric_as_of,
                            "source_text": (p.get("_provider_by_metric") or {}).get(key),
                            "source_title": (p.get("_source_title_by_metric") or {}).get(key),
                            "src_id": p["_fin_src"] if src_kind == "fin" else p["_val_src"]})
        valuation_metrics = [metric for metric in metrics if metric["source_kind"] == "val"]
        financial_metrics = [metric for metric in metrics if metric["source_kind"] == "fin"]
        company_cards.append({
            "company_id": p["company_id"], "name": p["company_name"], "ticker": p.get("ticker"),
            "listing_status": p.get("listing_status"), "is_unlisted": p["is_unlisted"],
            "industry_role": p.get("industry_role"),
            "comparison_group": p.get("comparison_group_label"),
            "group_color": p.get("valuation_color"),
            "display_note": p.get("display_note"),
            "metrics": metrics,
            "valuation_metrics": valuation_metrics,
            "financial_metrics": financial_metrics,
            "val_as_of": max(
                (metric["as_of"] for metric in valuation_metrics if metric.get("as_of")),
                default=None,
            ),
            "fin_as_of": max(
                (metric["as_of"] for metric in financial_metrics if metric.get("as_of")),
                default=None,
            ),
            "val_src": (
                None if p.get("_financial_authority_applied")
                else p["_val_src"]
            ),
            "fin_src": (
                None if p.get("_financial_authority_applied")
                else p["_fin_src"]
            ),
            "fc": {
                "rev1": p.get("forecast_revenue_year1"), "rev2": p.get("forecast_revenue_year2"),
                "eps1": p.get("forecast_eps_year1"), "eps2": p.get("forecast_eps_year2"),
                "unit": p.get("forecast_revenue_unit") or "", "as_of": p.get("forecast_as_of_date"),
                "src_id": p["_fc_src"],
                "source_text": p.get("_forecast_provider"),
                "source_title": p.get("_forecast_source_title"),
                "has": (p.get("forecast_revenue_year1") is not None or p.get("forecast_eps_year1") is not None),
            },
            "private": {
                "value": p.get("private_valuation_value"), "unit": p.get("private_valuation_unit") or "",
                "round": p.get("private_round"), "as_of": p.get("private_valuation_as_of"),
                "src_id": p["_priv_src"],
                "has": p.get("private_valuation_value") is not None,
            },
        })

    coverage = {
        "total": len(valuation_rows),
        "all_entities": len(rows),
        "excluded": len(excluded_rows),
        "with_valuation": sum(1 for p in valuation_rows if _positive_pe(p.get("pe_ttm")) or p.get("pb") is not None),
        "with_forecast": len(forecast_rows),
        "unlisted": sum(1 for p in valuation_rows if p["is_unlisted"]),
        "with_six": sum(1 for p in valuation_rows
                        if _positive_pe(p.get("pe_ttm"))
                        and all(p.get(k) is not None for k in VALUATION_CORE_KEYS if k != "pe_ttm")),
    }

    copper_peer_groups = []
    copper_pe_exclusions = []
    if is_copper:
        copper_pe_exclusions = [
            {
                "company_id": p["company_id"],
                "name": p["company_name"],
                "reason": "当前没有正的可比较TTM PE（亏损或接口未返回有效正值）",
            }
            for p in valuation_rows
            if not _positive_pe(p.get("pe_ttm"))
            and p.get("pb") is not None
            and p.get("roe") is not None
        ]
        group_analysis = {
            "资源矿山": (
                "资源矿山组的利润最直接受权益产量、现金成本和铜价驱动。紫金矿业"
                "资产最分散，洛阳钼业的刚果（金）铜钴利润密度高，五矿资源对"
                "Las Bambas与Khoemacau更敏感；西部矿业提供境内玉龙铜矿参照，"
                "中国有色矿业则体现赞比亚矿冶与港股折价。"
            ),
            "矿冶一体化": (
                "江西铜业、铜陵有色和云南铜业都有冶炼收入放大，PE/PB不能直接"
                "与纯矿山解释为同一种铜价弹性。组内更应比较自有矿比例、加工费、"
                "副产品收益、库存与营运资金，而不是营业收入规模。"
            ),
            "铜加工材料": (
                "海亮股份和金田股份主要依靠规模、加工费和周转效率，博威合金更多"
                "依靠高端铜合金配方与客户认证且含非铜业务。三家公司对铜价上涨的"
                "直接利润弹性弱于矿山，估值差异应由产品附加值和资本回报解释。"
            ),
        }
        for category in ("资源矿山", "矿冶一体化", "铜加工材料"):
            members = [p for p in valuation_rows if p.get("valuation_track") == category]
            medians = {}
            for key in ("pe_ttm", "pb", "roe", "roa"):
                values = []
                for member in members:
                    try:
                        value = float(member.get(key))
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(value) and (
                        key not in {"pe_ttm", "pb"} or value > 0
                    ):
                        values.append(value)
                medians[key] = median(values) if values else None
            copper_peer_groups.append(
                {
                    "name": category,
                    "color": next(
                        (
                            member.get("valuation_color")
                            for member in members
                            if member.get("valuation_region") == "A股"
                        ),
                        members[0].get("valuation_color") if members else "#64748b",
                    ),
                    "analysis": group_analysis[category],
                    "medians": medians,
                    "companies": [
                        {
                            "company_id": member["company_id"],
                            "name": member["company_name"],
                            "ticker": member.get("ticker"),
                            "market": member.get("valuation_region"),
                            "color": member.get("valuation_color"),
                            "pe_ttm": member.get("pe_ttm"),
                            "pb": member.get("pb"),
                            "roe": member.get("roe"),
                            "roa": member.get("roa"),
                        }
                        for member in members
                    ],
                }
            )

    if is_pcb_equipment:
        direct_rows = [p for p in valuation_rows if p.get("is_direct_pcb_comparable")]
        visualizations = {
            "pe_roe": None,
            "pb_roe": None,
            "heatmap": _valuation_heatmap(
                direct_rows,
                (("pe_ttm", "PE"), ("pb", "PB"), ("ps_ttm", "PS"), ("ev_ebitda", "EV/EBITDA")),
                colorscale=PCB_VALUATION_HEATMAP_COLORSCALE,
            ),
        }
    else:
        visualizations = {
            "pe_roe": _valuation_scatter(rows, "pe_ttm", "PE (TTM)"),
            "pb_roe": _valuation_scatter(rows, "pb", "PB"),
            "pb_roa": (
                _valuation_scatter(
                    rows,
                    "pb",
                    "PB",
                    ykey="roa",
                    ylabel="ROA (%)",
                )
                if is_copper
                else None
            ),
            "heatmap": _valuation_heatmap(rows),
        }

    # Static Markdown owns methodology, boundaries, reverse checks and the
    # research conclusion; structured cards below keep using current finance
    # observations. This mirrors the company-perspective separation.
    valuation_report = load_md(
        DOCS_DIR / "industries" / f"{ind['name']}_估值对比.md"
    )
    if valuation_report.get("exists"):
        valuation_report["html"] = wrap_markdown_tables_for_scroll(
            str(valuation_report["html"])
        )

    return render_template(
        "industry_valuation.html",
        ind=ind,
        q_dimensions=industry_q_dimensions(ind["name"]),
        metric_tables=metric_tables,
        forecast_rows=forecast_rows,
        private_rows=private_rows,
        company_cards=company_cards,
        coverage=coverage,
        excluded_rows=excluded_rows,
        compare_profitability=not is_pcb_equipment,
        is_pcb_equipment=is_pcb_equipment,
        is_copper=is_copper,
        copper_peer_groups=copper_peer_groups,
        copper_pe_exclusions=copper_pe_exclusions,
        core_keys=VALUATION_CORE_KEYS,
        visualizations_json=json.dumps(visualizations),
        valuation_report=valuation_report,
    )

# ── 路由:研究员补充 / 反共识(Stage 2c-F 任务 D,梁总点名)────
# analyst_note:任意实体的自由补充笔记;company_thesis:每公司反共识四件套。
# CC 绝不预填(空白默认),内容全部 user 写。作者第一版 hardcode 'zhengze'。
def _note_payload():
    """支持 form 或 JSON body。"""
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict() if request.form else {}


def _normalize_note_entity_id(entity_type: str, raw: Any) -> str:
    value = str(raw or "").strip()
    if entity_type == "theme":
        if not value:
            raise ValueError("theme id is empty")
        return value
    return str(int(value))


@app.route("/api/user-content/session", methods=["GET"])
def api_user_content_session():
    if not app.config.get("HONGHU_USER_CONTENT_SECURITY_READY"):
        return jsonify(
            {
                "ok": True,
                "security_ready": False,
                "authenticated": False,
                "mutation_enabled": False,
            }
        )
    try:
        principal = current_user_content_principal(app, request)
        return jsonify(
            {
                "ok": True,
                "security_ready": True,
                "authenticated": principal is not None,
                "principal": principal.subject if principal else None,
                "permissions": sorted(principal.permissions) if principal else [],
                "csrf_token": ensure_user_content_csrf_token(app),
                "mutation_enabled": bool(
                    principal and "analyst_note:write" in principal.permissions
                ),
            }
        )
    except Exception as exc:
        return _user_content_error(exc)


@app.route("/api/user-content/login", methods=["POST"])
def api_user_content_login():
    d = _note_payload()
    try:
        principal = authenticate_user_content(
            app,
            request,
            subject=str(d.get("subject") or "").strip(),
            password=str(d.get("password") or ""),
            csrf_token=str(request.headers.get("X-CSRF-Token") or d.get("csrf_token") or ""),
        )
        return jsonify(
            {
                "ok": True,
                "principal": principal.subject,
                "permissions": sorted(principal.permissions),
                "csrf_token": ensure_user_content_csrf_token(app),
            }
        )
    except Exception as exc:
        return _user_content_error(exc)


@app.route("/api/user-content/logout", methods=["POST"])
def api_user_content_logout():
    try:
        require_user_content_principal(
            app, request, permission="analyst_note:read", csrf=True
        )
        clear_user_content_principal()
        return jsonify({"ok": True})
    except Exception as exc:
        return _user_content_error(exc)


@app.route("/api/analyst_note", methods=["POST"])
def api_analyst_note_create():
    try:
        # Transport, authentication and CSRF are security boundaries, so they
        # must run before payload validation.  Otherwise a malformed mutation
        # sent to plaintext HTTP can return a business-validation 400 and make
        # the HTTPS fail-closed gate appear to have been bypassed.
        principal = require_user_content_principal(
            app, request, permission="analyst_note:write", csrf=True
        )
        d = _note_payload()
        entity_type = (d.get("entity_type") or "").strip()
        content = (d.get("content") or "").strip()
        if entity_type not in ("company", "industry", "industry_q", "theme") or not content:
            return jsonify({"ok": False, "error": "entity_type 非法或 content 为空"}), 400
        try:
            entity_id = _normalize_note_entity_id(entity_type, d.get("entity_id"))
        except Exception:
            return jsonify({"ok": False, "error": "entity_id 非法"}), 400
        expected_revision = int(d.get("expected_revision", 0))
        idempotency_key = str(
            request.headers.get("X-Idempotency-Key") or d.get("idempotency_key") or ""
        ).strip()
        if not idempotency_key:
            return jsonify(
                {"ok": False, "error": "缺少 idempotency key", "code": "idempotency_required"}
            ), 400
        note_key = str(d.get("note_key") or f"note:{uuid.uuid4()}").strip()
        entity_key = analyst_note_entity_key(entity_type, entity_id)
        mutation = AnalystNoteMutation(
            note_key=note_key,
            entity_type=entity_type,
            legacy_entity_id=entity_id,
            entity_key=entity_key,
            q_label=(str(d.get("q_number")).strip() if d.get("q_number") else None),
            note_type=str(d.get("note_type") or "general").strip(),
            title=(str(d.get("title")).strip() if d.get("title") else None),
            content=content,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )
        note = analyst_note_repository().put(mutation, actor=principal.subject)
        return jsonify({"ok": True, "note": note.to_dict()})
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "expected_revision 非法"}), 400
    except Exception as exc:
        return _user_content_error(exc)


@app.route("/api/analyst_note/<entity_type>/<entity_id>", methods=["GET"])
def api_analyst_note_list(entity_type: str, entity_id: str):
    q_number = (request.args.get("q") or "").strip()
    try:
        if entity_type not in ("company", "industry", "industry_q", "theme"):
            return jsonify({"ok": False, "error": "entity_type 非法"}), 400
        entity_id = _normalize_note_entity_id(entity_type, entity_id)
        require_user_content_principal(
            app, request, permission="analyst_note:read", csrf=False
        )
        entity_key = analyst_note_entity_key(entity_type, entity_id)
        notes = analyst_note_repository().list_notes(
            entity_type=entity_type,
            legacy_entity_id=entity_id,
            entity_key=entity_key,
            q_label=q_number or None,
        )
        return jsonify({"ok": True, "notes": [note.to_dict() for note in notes]})
    except Exception as exc:
        return _user_content_error(exc)


def _delete_analyst_note(note_key: str, *, principal=None):
    try:
        principal = principal or require_user_content_principal(
            app, request, permission="analyst_note:write", csrf=True
        )
        d = _note_payload()
        expected_revision = int(d.get("expected_revision"))
        idempotency_key = str(
            request.headers.get("X-Idempotency-Key") or d.get("idempotency_key") or ""
        ).strip()
        if not idempotency_key:
            return jsonify(
                {"ok": False, "error": "缺少 idempotency key", "code": "idempotency_required"}
            ), 400
        note = analyst_note_repository().soft_delete(
            note_key=note_key,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            actor=principal.subject,
        )
        return jsonify({"ok": True, "note": note.to_dict()})
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "expected_revision 非法"}), 400
    except Exception as exc:
        return _user_content_error(exc)


@app.route("/api/analyst_note/<int:note_id>", methods=["DELETE"])
def api_analyst_note_delete(note_id: int):
    try:
        # Authorize before resolving the legacy id so a plaintext request
        # cannot reach repository reads or return object-specific errors.
        principal = require_user_content_principal(
            app, request, permission="analyst_note:write", csrf=True
        )
        note_key = analyst_note_repository().note_key_from_legacy_id(note_id)
        return _delete_analyst_note(note_key, principal=principal)
    except Exception as exc:
        return _user_content_error(exc)


@app.route("/api/analyst_note/key/<path:note_key>", methods=["DELETE"])
def api_analyst_note_delete_by_key(note_key: str):
    return _delete_analyst_note(note_key)


@app.route("/api/company_thesis", methods=["POST"])
def api_company_thesis_upsert():
    """2c-G:研究员手填 contrarian_thesis + monitoring_signals(证实/证伪合并)+ conviction。
    consensus_view 若由人工编辑提交(edit_consensus=1),覆盖 AI 版并切 author=人工。"""
    d = _note_payload()
    try:
        company_id = int(d.get("company_id"))
    except Exception:
        return jsonify({"ok": False, "error": "company_id 非法"}), 400
    industry_id = d.get("industry_id")
    try:
        industry_id = int(industry_id) if industry_id not in (None, "", "null") else None
    except Exception:
        industry_id = None
    conv = d.get("conviction_level")
    try:
        conv = int(conv) if conv not in (None, "", "null") else None
    except Exception:
        conv = None
    author = (d.get("author") or "zhengze")
    edit_consensus = str(d.get("edit_consensus") or "").strip() in ("1", "true", "True")
    conn = get_domain_write_db("investment_hypotheses", "company_thesis_upsert")
    try:
        existing = conn.execute(
            "SELECT id FROM company_thesis WHERE company_id=? AND IFNULL(industry_id,-1)=IFNULL(?,-1)",
            (company_id, industry_id),
        ).fetchone()
        if existing:
            tid = existing[0]
            conn.execute(
                """UPDATE company_thesis SET contrarian_thesis=?, monitoring_signals=?,
                   conviction_level=?, author=?, updated_at=datetime('now','localtime') WHERE id=?""",
                (d.get("contrarian_thesis"), d.get("monitoring_signals"), conv, author, tid),
            )
            if edit_consensus:  # 人工覆盖 AI 一致预期 → 清生成时间戳,留人工痕迹
                conn.execute(
                    "UPDATE company_thesis SET consensus_view=?, consensus_generated_at=NULL WHERE id=?",
                    (d.get("consensus_view"), tid),
                )
        else:
            cur = conn.execute(
                """INSERT INTO company_thesis(company_id, industry_id, consensus_view,
                   contrarian_thesis, monitoring_signals, conviction_level, author)
                   VALUES(?,?,?,?,?,?,?)""",
                (company_id, industry_id, (d.get("consensus_view") if edit_consensus else None),
                 d.get("contrarian_thesis"), d.get("monitoring_signals"), conv, author),
            )
            tid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "thesis": query_one("SELECT * FROM company_thesis WHERE id=?", (tid,))})


# ── 路由:行业级 thesis(2c-G 任务 3B + 4)────────────
@app.route("/api/industry_thesis/<int:industry_id>", methods=["GET"])
def api_industry_thesis_get(industry_id: int):
    return jsonify({"ok": True, "thesis": query_one(
        "SELECT * FROM industry_thesis WHERE industry_id=?", (industry_id,))})


@app.route("/api/industry_thesis/<int:industry_id>", methods=["POST"])
def api_industry_thesis_upsert(industry_id: int):
    """研究员反共识 + 监控指标 + 信心度;edit_consensus=1 时人工覆盖 AI 散文(置 overridden=1)。"""
    d = _note_payload()
    conv = d.get("conviction_level")
    try:
        conv = int(conv) if conv not in (None, "", "null") else None
    except Exception:
        conv = None
    author = (d.get("author") or "zhengze")
    edit_consensus = str(d.get("edit_consensus") or "").strip() in ("1", "true", "True")
    conn = get_domain_write_db("investment_hypotheses", "industry_thesis_upsert")
    try:
        existing = conn.execute("SELECT id FROM industry_thesis WHERE industry_id=?", (industry_id,)).fetchone()
        if existing:
            tid = existing[0]
            conn.execute(
                """UPDATE industry_thesis SET contrarian_thesis=?, monitoring_signals=?,
                   conviction_level=?, author=?, updated_at=datetime('now','localtime') WHERE id=?""",
                (d.get("contrarian_thesis"), d.get("monitoring_signals"), conv, author, tid),
            )
            if edit_consensus:  # 人工覆盖 AI 散文 → overridden=1
                conn.execute(
                    """UPDATE industry_thesis SET consensus_narrative=?,
                       consensus_overridden_by_human=1, consensus_generated_at=datetime('now','localtime')
                       WHERE id=?""",
                    (d.get("consensus_narrative"), tid),
                )
        else:
            cur = conn.execute(
                """INSERT INTO industry_thesis(industry_id, consensus_narrative,
                   consensus_overridden_by_human, contrarian_thesis, monitoring_signals,
                   conviction_level, author) VALUES(?,?,?,?,?,?,?)""",
                (industry_id, (d.get("consensus_narrative") if edit_consensus else None),
                 (1 if edit_consensus else 0),
                 d.get("contrarian_thesis"), d.get("monitoring_signals"), conv, author),
            )
            tid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "thesis": query_one("SELECT * FROM industry_thesis WHERE id=?", (tid,))})


@app.route("/api/industry_thesis/<int:industry_id>/regenerate", methods=["POST"])
def api_industry_thesis_regenerate(industry_id: int):
    """ 重新生成 AI 版本。本轮 AI 散文由 CC session 生成(非 API),
    故此端点不在请求内实时生成,仅回报状态:需重跑生成脚本 / 等 API token。"""
    return jsonify({
        "ok": False,
        "pending": True,
        "message": "本轮 AI 综合分析由 CC session 生成。重新生成请重跑 "
                   "tools/pipeline/stage2c_g_write_narrative_cc.py(CC 版),"
                   "或待 ANTHROPIC_API_KEY 到位后跑 stage2c_g_gen_consensus_narrative.py(API 版)。",
    })


@app.route("/api/company_thesis/<int:company_id>", methods=["GET"])
def api_company_thesis_get(company_id: int):
    industry_id = request.args.get("industry_id")
    if industry_id not in (None, "", "null"):
        row = query_one(
            "SELECT * FROM company_thesis WHERE company_id=? AND IFNULL(industry_id,-1)=IFNULL(?,-1)",
            (company_id, int(industry_id)),
        )
    else:
        row = query_one("SELECT * FROM company_thesis WHERE company_id=? ORDER BY updated_at DESC LIMIT 1", (company_id,))
    return jsonify({"ok": True, "thesis": row})


# ── 路由:事件日历(Stage 3-B)────────────────────────
from datetime import timedelta as _timedelta, date as _date2  # noqa: E402
IMPORTANCE_LABEL = {1: "L1 核心", 2: "L2 重要", 3: "L3 关注"}


def _resolve_entity_names(company_json, industry_json):
    """company: id 列表 → {id,name,ticker}。industry(v2 板块): 可能是 NAME 列表(新板块无 db id)
    或历史 id 列表;统一解析为 {id(or None), name},name 用于 5 色 chip,id 有则可点链。"""
    cids = _json_or([], company_json); raw_inds = _json_or([], industry_json)
    companies = []
    for cid in (cids if isinstance(cids, list) else []):
        r = query_one("SELECT id, name, ticker FROM company WHERE id=?", (cid,))
        if r:
            companies.append(r)
    industries = []
    for v in (raw_inds if isinstance(raw_inds, list) else []):
        if isinstance(v, int):                       # 历史:id
            r = query_one("SELECT id, name FROM industry WHERE id=?", (v,))
            if r:
                industries.append(r)
        else:                                        # v2:板块名(新板块 db 可能无 id)
            r = query_one("SELECT id, name FROM industry WHERE name=?", (str(v),))
            industries.append(r if r else {"id": None, "name": str(v)})
    return companies, industries


def _enrich_event(e):
    e["importance_label"] = IMPORTANCE_LABEL.get(e.get("importance"), "L3 关注")
    e["companies"], e["industries"] = _resolve_entity_names(
        e.get("related_company_ids"), e.get("related_industry_ids"))
    try:
        d = _date2.fromisoformat((e.get("scheduled_date") or "")[:10])
        e["weekday"] = "一二三四五六日"[d.weekday()]
    except Exception:
        e["weekday"] = ""
    return e


@app.route("/events")
def events_index():
    today = _date2.today()
    end_week = today + _timedelta(days=(6 - today.weekday()))            # 本周日
    start_next = end_week + _timedelta(days=1); end_next = start_next + _timedelta(days=6)
    # 本月末
    if today.month == 12:
        end_month = _date2(today.year, 12, 31)
    else:
        end_month = _date2(today.year, today.month + 1, 1) - _timedelta(days=1)

    upcoming = [_enrich_event(e) for e in query_all(
        "SELECT * FROM event WHERE scheduled_date >= ? AND status IN ('upcoming','confirmed','rumored') "
        "ORDER BY scheduled_date ASC, importance ASC", (today.isoformat(),))]

    def bucket(lo, hi):
        return [e for e in upcoming if lo.isoformat() <= (e["scheduled_date"] or "")[:10] <= hi.isoformat()]

    return render_template(
        "events.html",
        week=bucket(today, end_week),
        next_week=bucket(start_next, end_next),
        month=bucket(today, end_month),
        upcoming=upcoming,
        total=len(upcoming),
        today=today.isoformat(),
    )


@app.route("/event/<int:event_id>")
def event_detail(event_id: int):
    e = query_one("SELECT * FROM event WHERE id=?", (event_id,))
    if not e:
        abort(404, f"event id={event_id} 不存在")
    _enrich_event(e)
    e["preview_html"] = render_markdown(e["ai_preview_narrative"]) if e.get("ai_preview_narrative") else ""
    e["recap_html"] = render_markdown(e["ai_recap_narrative"]) if e.get("ai_recap_narrative") else ""
    e["preview_src_ids"] = _json_or([], e.get("ai_preview_source_ids"))
    # 关联新闻 / 推文(FK 反查,防 dangling)
    rel_news = query_all("SELECT id, title, url, source_publisher, publish_date FROM news_item "
                         "WHERE ai_tags_event_id=? ORDER BY publish_date DESC", (event_id,))
    rel_voice = query_all(
        "SELECT vp.id, vp.content_text, vp.post_url, vp.posted_at, ol.name AS leader_name, ol.platform "
        "FROM voice_post vp JOIN opinion_leader ol ON ol.id=vp.leader_id "
        "WHERE vp.ai_tags_event_id=? ORDER BY vp.posted_at DESC", (event_id,))
    return render_template("event_detail.html", e=e, rel_news=rel_news, rel_voice=rel_voice)


@app.route("/api/event", methods=["POST"])
def api_event_create():
    d = _note_payload()
    try:
        imp = int(d.get("importance"))
    except Exception:
        return jsonify({"ok": False, "error": "importance 须为 1/2/3"}), 400
    def _ids(v):
        if isinstance(v, list):
            return v
        if v in (None, ""):
            return []
        try:
            return json.loads(v)
        except Exception:
            return [x.strip() for x in str(v).split(",") if x.strip()]
    conn = get_domain_write_db("dynamic_intelligence", "manual_event_create")
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "tools" / "dynamic"))
        import event_store
        ok, msg, eid = event_store.insert_manual(
            conn, title=(d.get("title") or "").strip(), event_type=(d.get("event_type") or "").strip(),
            scheduled_date=(d.get("scheduled_date") or "").strip(), importance=imp,
            related_company_ids=_ids(d.get("related_company_ids")),
            related_industry_ids=_ids(d.get("related_industry_ids")),
            description=d.get("description"), official_url=d.get("official_url"))
    finally:
        conn.close()
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400
    return jsonify({"ok": True, "event_id": eid})


@app.route("/api/event/<int:event_id>/analyst", methods=["POST"])
def api_event_analyst(event_id: int):
    """研究员前瞻/事后 手填(CC 不预填)。"""
    d = _note_payload()
    field = (d.get("field") or "").strip()      # analyst_preview / analyst_recap
    if field not in ("analyst_preview", "analyst_recap"):
        return jsonify({"ok": False, "error": "field 须为 analyst_preview/analyst_recap"}), 400
    author = (d.get("author") or "zhengze")
    conn = get_domain_write_db("dynamic_intelligence", "manual_event_analyst_update")
    try:
        if not conn.execute("SELECT 1 FROM event WHERE id=?", (event_id,)).fetchone():
            return jsonify({"ok": False, "error": "event 不存在"}), 404
        conn.execute(
            f"UPDATE event SET {field}=?, {field}_author=?, {field}_updated_at=datetime('now','localtime') "
            f"WHERE id=?", (d.get("content"), author, event_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


# ── 路由:行业新闻流(Stage 3-C)────────────────────────
def _enrich_news(n):
    n["companies"], n["industries"] = _resolve_entity_names(
        n.get("ai_tags_company"), n.get("ai_tags_industry"))
    n["is_gray"] = (n.get("source_credibility") == "unverified")
    n["when"] = (n.get("publish_date") or (n.get("fetch_timestamp") or "")[:10] or "")
    return n


def _parse_int_csv(s):
    return [int(x) for x in (s or "").split(",") if x.strip().isdigit()]


@app.route("/dynamic/news")
def dynamic_news():
    show_all = request.args.get("all") == "1"        # P2.1:?all=1 显示 is_ai_relevant=0
    f_inds = _parse_int_csv(request.args.get("industry"))   # ?industry=8,14
    f_imps = _parse_int_csv(request.args.get("importance")) # ?importance=1,2
    where = [] if show_all else ["(n.is_ai_relevant=1 OR n.is_ai_relevant IS NULL)"]
    params = []
    if f_inds:   # JSON 字段筛选(ai_tags_industry 含任一 id)
        where.append("(" + " OR ".join("n.ai_tags_industry LIKE ?" for _ in f_inds) + ")")
        params += [f'%{i}%' for i in f_inds]
    if f_imps:
        where.append("n.importance IN (" + ",".join("?" for _ in f_imps) + ")")
        params += f_imps
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = [_enrich_news(n) for n in query_all(f"""
        SELECT n.*, s.source_credibility, s.quality_tier, s.language AS src_lang
        FROM news_item n LEFT JOIN source s ON s.id = n.source_id
        {wsql}
        ORDER BY n.is_breaking DESC, COALESCE(n.publish_date, n.fetch_timestamp) DESC, n.importance ASC
        LIMIT 200""", tuple(params))]
    # 联动:命中研究员假说的监控关键词 →  badge(只标红提示,不判断触发)
    kw_index = []
    for s in query_all("SELECT sg.ai_check_keywords, sg.hypothesis_id, h.title "
                       "FROM hypothesis_monitoring_signal sg JOIN hypothesis h ON h.id=sg.hypothesis_id "
                       "WHERE h.is_draft=0"):
        for k in _kw_list(s["ai_check_keywords"]):
            if k:
                kw_index.append((k, s["hypothesis_id"], s["title"]))
    if kw_index:
        for n in rows:
            hay = (n.get("title") or "") + " " + (n.get("title_zh") or "") + " " + (n.get("summary") or "")
            seen = {}
            for k, hid, title in kw_index:
                if k in hay:
                    seen[hid] = title
            if seen:
                n["related_hyps"] = [{"id": hid, "title": title} for hid, title in seen.items()]

    totals = {
        "total": query_one("SELECT COUNT(*) AS n FROM news_item")["n"],
        "shown": len(rows),
        "breaking": query_one("SELECT COUNT(*) AS n FROM news_item WHERE is_breaking=1")["n"],
    }
    boards = query_all("SELECT id, name FROM industry ORDER BY (tier=1) DESC, id")
    return render_template("news.html", news=rows, totals=totals, boards=boards,
                           f_inds=f_inds, f_imps=f_imps, show_all=show_all)


# ── 路由:意见领袖观点流(Stage 3-D)────────────────────
@app.route("/dynamic/voices")
def dynamic_voices():
    show_all = request.args.get("all") == "1"
    f_leader = request.args.get("leader")
    f_inds = _parse_int_csv(request.args.get("industry"))
    f_ptype = (request.args.get("post_type") or "").strip()
    where = [] if show_all else ["(vp.is_ai_relevant=1 OR vp.is_ai_relevant IS NULL)"]
    params = []
    if f_leader and f_leader.isdigit():
        where.append("vp.leader_id=?"); params.append(int(f_leader))
    if f_inds:
        where.append("(" + " OR ".join("vp.ai_tags_industry LIKE ?" for _ in f_inds) + ")")
        params += [f'%{i}%' for i in f_inds]
    if f_ptype in ("观点", "数据", "转发", "提问", "闲聊"):
        where.append("vp.post_type=?"); params.append(f_ptype)
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = query_all(f"""
        SELECT vp.*, ol.name AS leader_name, ol.platform, ol.profile_url,
               ol.source_id AS leader_source_id, s.note AS leader_note
        FROM voice_post vp JOIN opinion_leader ol ON ol.id = vp.leader_id
        LEFT JOIN source s ON s.id = ol.source_id
        {wsql}
        ORDER BY vp.posted_at DESC LIMIT 120""", tuple(params))
    voices = []
    for v in rows:
        if (v.get("post_type") == "闲聊") and not show_all and f_ptype != "闲聊":
            continue
        v["companies"], v["industries"] = _resolve_entity_names(
            v.get("ai_tags_company"), v.get("ai_tags_industry"))
        v["verified_kol"] = (v.get("leader_note") == "verified_kol")
        voices.append(v)
    # P3:领袖卡片 —— 默认只显示"精选(is_featured)"少数索引;?all_leaders=1 展开全部 active。
    show_all_leaders = request.args.get("all_leaders") == "1"
    feat_sql = "" if show_all_leaders else " AND ol.is_featured=1"
    leaders = query_all(f"""
        SELECT ol.id, ol.name, ol.platform, ol.region, ol.bio, ol.expertise_tags, ol.is_featured, s.note,
               (SELECT COUNT(*) FROM voice_post vp WHERE vp.leader_id=ol.id) AS n,
               (SELECT fs.status FROM fetch_schedule fs WHERE fs.target_type='voice_leader' AND fs.target_id=ol.id) AS fetch_status
        FROM opinion_leader ol LEFT JOIN source s ON s.id=ol.source_id
        WHERE ol.is_active=1{feat_sql} ORDER BY ol.is_featured DESC, ol.id""")
    for L in leaders:
        L["expertise_list"] = _json_or([], L.get("expertise_tags"))
        L["verified_kol"] = (L.get("note") == "verified_kol")
    leader_counts = {
        "active": query_one("SELECT COUNT(*) AS n FROM opinion_leader WHERE is_active=1")["n"],
        "featured": query_one("SELECT COUNT(*) AS n FROM opinion_leader WHERE is_active=1 AND is_featured=1")["n"],
    }
    # 完整领袖下拉(筛选用,含未精选)
    all_leaders = query_all(
        "SELECT id, name, is_featured FROM opinion_leader WHERE is_active=1 ORDER BY is_featured DESC, id")
    # 选中单个领袖时:顶部个人页头(是谁 + 擅长什么)
    lead_profile = None
    if f_leader and f_leader.isdigit():
        lp = query_one("""SELECT ol.*, (SELECT COUNT(*) FROM voice_post vp WHERE vp.leader_id=ol.id) AS n
                          FROM opinion_leader ol WHERE ol.id=?""", (int(f_leader),))
        if lp:
            lp["expertise_list"] = _json_or([], lp.get("expertise_tags"))
            lead_profile = lp
    totals = {"total": query_one("SELECT COUNT(*) AS n FROM voice_post")["n"], "shown": len(voices),
              "tagged": query_one("SELECT COUNT(*) AS n FROM voice_post WHERE ai_tagged_by IS NOT NULL")["n"]}
    boards = query_all("SELECT id, name FROM industry ORDER BY (tier=1) DESC, id")
    return render_template("voices.html", voices=voices, leaders=leaders, totals=totals,
                           boards=boards, f_leader=f_leader, f_inds=f_inds, f_ptype=f_ptype,
                           show_all_leaders=show_all_leaders, leader_counts=leader_counts,
                           all_leaders=all_leaders, lead_profile=lead_profile)


# ════════════════════════════════════════════════════════════════════
#  Stage 4-A:研究员投资假说模块(以人为标签 · 假说 + 证伪条件 + 双向交易)
#   反 slop:CC 只搭骨架,内容全人手填;引用 id 必须 db 真实存在(dangling halt);
#    AI 监控仅标红推送,不判断"已触发",不给买卖建议;hypothesis_update append-only。
# ════════════════════════════════════════════════════════════════════

# 假说域中文标签(独立于全局 t():避免 active 等枚举跨域冲突)
HYP_LABEL = {
    # thesis_type
    "bullish": "看多", "bearish": "看空", "neutral": "中性", "contrarian": "反共识",
    # hypothesis.status
    "active": "跟踪中", "partially_falsified": "部分证伪", "falsified": "已证伪",
    "confirmed": "已确认", "withdrawn": "已撤回",
    # signal_type
    "falsification": "证伪条件", "confirmation": "确认信号", "monitor": "中性观察",
    # signal.current_status
    "not_triggered": "未触发", "partially_triggered": "部分触发",
    "triggered": "已触发", "contradicted": "被反驳",
    # trade_scenario
    "primary": "正向交易", "falsification_reverse": "证伪后反向",
    # trade.direction
    "long": "做多", "short": "做空", "pair": "配对",
    # trade.status(active 在交易语境=已建仓,模板单独处理)
    "proposed": "提议", "closed_profit": "止盈平仓", "closed_loss": "止损平仓", "abandoned": "放弃",
}
TRADE_STATUS_LABEL = {**HYP_LABEL, "active": "已建仓"}


def hl(x: Any) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    return HYP_LABEL.get(s, s)


def trade_status_label(x: Any) -> str:
    return TRADE_STATUS_LABEL.get(str(x or "").strip(), str(x or ""))


app.jinja_env.globals["hl"] = hl
app.jinja_env.globals["trade_status_label"] = trade_status_label

THESIS_TYPES = ("bullish", "bearish", "neutral", "contrarian")
HYP_STATUSES = ("active", "partially_falsified", "falsified", "confirmed", "withdrawn")


def _as_id_list(v) -> List[int]:
    """coerce → [int]。接受 list / JSON 串 / 逗号串。"""
    if v in (None, ""):
        return []
    if isinstance(v, int):
        return [v]
    if isinstance(v, list):
        out = []
        for x in v:
            try:
                out.append(int(x))
            except Exception:
                pass
        return out
    try:
        j = json.loads(v)
        if isinstance(j, list):
            return [int(x) for x in j if str(x).strip().lstrip("-").isdigit()]
    except Exception:
        pass
    return [int(x) for x in str(v).split(",") if x.strip().isdigit()]


def _kw_list(v) -> List[str]:
    if v in (None, ""):
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    try:
        j = json.loads(v)
        if isinstance(j, list):
            return [str(x).strip() for x in j if str(x).strip()]
    except Exception:
        pass
    return [x.strip() for x in str(v).split(",") if x.strip()]


def _dump(lst):
    """[ids/kw] → JSON 串 or None(空不存空串,存 NULL)。"""
    return json.dumps(lst, ensure_ascii=False) if lst else None


def _check_dangling(conn, table: str, ids: List[int]) -> List[int]:
    """返回 db 中不存在的 id(dangling)。"""
    bad = []
    for i in ids:
        if not conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (i,)).fetchone():
            bad.append(i)
    return bad


def _resolve_researcher(rid):
    return query_one("SELECT * FROM researcher WHERE id=?", (rid,))


def _hyp_signal_summary(hid: int) -> Dict[str, int]:
    rows = query_all(
        "SELECT current_status, COUNT(*) c FROM hypothesis_monitoring_signal "
        "WHERE hypothesis_id=? GROUP BY current_status", (hid,))
    summ = {"total": 0, "triggered": 0, "partially_triggered": 0, "not_triggered": 0, "contradicted": 0}
    for r in rows:
        summ[r["current_status"]] = r["c"]
        summ["total"] += r["c"]
    return summ


def _hyp_enrich(h: Dict[str, Any]) -> Dict[str, Any]:
    """补研究员名 + tag 名 + 信号/交易摘要(列表卡片用)。"""
    r = _resolve_researcher(h.get("researcher_id"))
    h["researcher_name"] = r["display_name"] or r["name"] if r else "(未知)"
    h["companies"], h["industries"] = _resolve_entity_names(
        h.get("related_company_ids"), h.get("related_industry_ids"))
    h["signal_summary"] = _hyp_signal_summary(h["id"])
    h["trades"] = query_all(
        "SELECT * FROM hypothesis_trade WHERE hypothesis_id=? ORDER BY trade_scenario, display_order, id", (h["id"],))
    return h


def _resolve_citations(h: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """假说引用 id → 可显示条目(只取 db 真实存在的;dangling 静默丢弃)。"""
    out = {"sources": [], "news": [], "voices": [], "events": []}
    for sid in _as_id_list(h.get("cite_source_ids")):
        r = query_one("SELECT id, title, quality_tier FROM source WHERE id=?", (sid,))
        if r:
            out["sources"].append(r)
    for nid in _as_id_list(h.get("cite_news_ids")):
        r = query_one("SELECT id, title, url, source_publisher, publish_date FROM news_item WHERE id=?", (nid,))
        if r:
            out["news"].append(r)
    for vid in _as_id_list(h.get("cite_voice_ids")):
        r = query_one("SELECT vp.id, vp.content_text, vp.post_url, vp.posted_at, ol.name AS leader_name "
                      "FROM voice_post vp JOIN opinion_leader ol ON ol.id=vp.leader_id WHERE vp.id=?", (vid,))
        if r:
            out["voices"].append(r)
    for eid in _as_id_list(h.get("cite_event_ids")):
        r = query_one("SELECT id, title, scheduled_date, event_type FROM event WHERE id=?", (eid,))
        if r:
            out["events"].append(r)
    return out


def _log_update(conn, hid, updated_by, update_type, note=None,
                snap_status=None, snap_text=None, snap_conv=None,
                news_id=None, event_id=None):
    """append hypothesis_update(版本化,绝不删旧)。"""
    conn.execute(
        """INSERT INTO hypothesis_update
           (hypothesis_id, updated_by, update_type, update_note,
            snapshot_status, snapshot_text, snapshot_conviction,
            triggered_by_news_id, triggered_by_event_id)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (hid, updated_by, update_type, note, snap_status, snap_text, snap_conv, news_id, event_id))


# ── 路由:假说总览 /hypotheses ───────────────────────────
@app.route("/hypotheses")
def hypotheses_index():
    f_researcher = request.args.get("researcher")
    f_inds = _parse_int_csv(request.args.get("industry"))
    f_status = (request.args.get("status") or "").strip()
    f_dir = (request.args.get("direction") or "").strip()
    show_drafts = request.args.get("drafts") == "1"
    where = [] if show_drafts else ["(h.is_draft=0 OR h.is_draft IS NULL)"]
    params: List[Any] = []
    if f_researcher and f_researcher.isdigit():
        where.append("h.researcher_id=?"); params.append(int(f_researcher))
    if f_inds:
        where.append("(" + " OR ".join("h.related_industry_ids LIKE ?" for _ in f_inds) + ")")
        params += [f"%{i}%" for i in f_inds]
    if f_status in HYP_STATUSES:
        where.append("h.status=?"); params.append(f_status)
    if f_dir in THESIS_TYPES:
        where.append("h.thesis_type=?"); params.append(f_dir)
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = [_hyp_enrich(h) for h in query_all(
        f"SELECT h.* FROM hypothesis h {wsql} "
        f"ORDER BY COALESCE(h.last_updated_at, h.created_at) DESC", tuple(params))]
    researchers = query_all("SELECT id, name, display_name FROM researcher WHERE is_active=1 ORDER BY id")
    boards = query_all("SELECT id, name FROM industry ORDER BY (tier=1) DESC, id")
    totals = {
        "total": query_one("SELECT COUNT(*) AS n FROM hypothesis WHERE is_draft=0")["n"],
        "drafts": query_one("SELECT COUNT(*) AS n FROM hypothesis WHERE is_draft=1")["n"],
        "researchers": query_one("SELECT COUNT(*) AS n FROM researcher WHERE is_active=1")["n"],
    }
    return render_template("hypothesis/list.html", hyps=rows, researchers=researchers,
                           boards=boards, totals=totals, f_researcher=f_researcher,
                           f_inds=f_inds, f_status=f_status, f_dir=f_dir, show_drafts=show_drafts)


# ── 路由:研究员个人主页 /researcher/<id> ────────────────
@app.route("/researcher/<int:rid>")
def researcher_profile(rid: int):
    r = _resolve_researcher(rid)
    if not r:
        abort(404, f"researcher id={rid} 不存在")
    r["focus_list"] = []
    for iid in _as_id_list(r.get("focus_industries")):
        row = query_one("SELECT id, name FROM industry WHERE id=?", (iid,))
        if row:
            r["focus_list"].append(row)
    hyps = [_hyp_enrich(h) for h in query_all(
        "SELECT * FROM hypothesis WHERE researcher_id=? AND is_draft=0 "
        "ORDER BY COALESCE(last_updated_at, created_at) DESC", (rid,))]
    stat = {"active": 0, "partially_falsified": 0, "falsified": 0, "confirmed": 0, "withdrawn": 0}
    for h in hyps:
        stat[h["status"]] = stat.get(h["status"], 0) + 1
    timeline = query_all(
        """SELECT hu.*, h.title AS hyp_title FROM hypothesis_update hu
           JOIN hypothesis h ON h.id=hu.hypothesis_id
           WHERE hu.updated_by=? ORDER BY hu.created_at DESC LIMIT 30""", (rid,))
    return render_template("researcher/profile.html", r=r, hyps=hyps, stat=stat, timeline=timeline)


# ── 路由:单条假说详情 /hypothesis/<id> ──────────────────
@app.route("/hypothesis/<int:hid>")
def hypothesis_detail(hid: int):
    h = query_one("SELECT * FROM hypothesis WHERE id=?", (hid,))
    if not h:
        abort(404, f"hypothesis id={hid} 不存在")
    _hyp_enrich(h)
    h["text_html"] = render_markdown(h.get("hypothesis_text") or "")
    signals = query_all(
        "SELECT * FROM hypothesis_monitoring_signal WHERE hypothesis_id=? "
        "ORDER BY (signal_type='falsification') DESC, display_order, id", (hid,))
    for s in signals:
        s["kw_list"] = _kw_list(s.get("ai_check_keywords"))
    trades = query_all(
        "SELECT * FROM hypothesis_trade WHERE hypothesis_id=? ORDER BY trade_scenario, display_order, id", (hid,))
    for tr in trades:
        tr["companies"], tr["industries"] = _resolve_entity_names(
            tr.get("target_company_ids"), tr.get("target_industry_ids"))
    updates = query_all(
        "SELECT hu.*, r.display_name AS by_name, r.name AS by_raw FROM hypothesis_update hu "
        "LEFT JOIN researcher r ON r.id=hu.updated_by WHERE hu.hypothesis_id=? "
        "ORDER BY hu.created_at DESC", (hid,))
    cites = _resolve_citations(h)
    researchers = query_all("SELECT id, name, display_name FROM researcher WHERE is_active=1 ORDER BY id")
    return render_template("hypothesis/detail.html", h=h, signals=signals, trades=trades,
                           updates=updates, cites=cites, researchers=researchers)


# ── 路由:新建假说表单 /hypothesis/new ───────────────────
@app.route("/hypothesis/new")
def hypothesis_new():
    researchers = query_all("SELECT id, name, display_name FROM researcher WHERE is_active=1 ORDER BY id")
    boards = query_all("SELECT id, name FROM industry ORDER BY (tier=1) DESC, id")
    companies = query_all("SELECT id, name, ticker FROM company ORDER BY name")
    prefill = {"mode": "new", "id": None, "h": None, "signals": [], "trades": [], "cites": None}
    return render_template("hypothesis/form.html", mode="new", h=None, signals=[], trades=[],
                           researchers=researchers, boards=boards, companies=companies,
                           cites=None, prefill=prefill)


# ── 路由:编辑假说 /hypothesis/<id>/edit ─────────────────
@app.route("/hypothesis/<int:hid>/edit")
def hypothesis_edit(hid: int):
    h = query_one("SELECT * FROM hypothesis WHERE id=?", (hid,))
    if not h:
        abort(404, f"hypothesis id={hid} 不存在")
    h["related_industry_ids_list"] = _as_id_list(h.get("related_industry_ids"))
    h["related_company_ids_list"] = _as_id_list(h.get("related_company_ids"))
    signals = query_all(
        "SELECT * FROM hypothesis_monitoring_signal WHERE hypothesis_id=? ORDER BY display_order, id", (hid,))
    for s in signals:
        s["kw_list"] = _kw_list(s.get("ai_check_keywords"))
    trades = query_all("SELECT * FROM hypothesis_trade WHERE hypothesis_id=? ORDER BY trade_scenario, id", (hid,))
    researchers = query_all("SELECT id, name, display_name FROM researcher WHERE is_active=1 ORDER BY id")
    boards = query_all("SELECT id, name FROM industry ORDER BY (tier=1) DESC, id")
    companies = query_all("SELECT id, name, ticker FROM company ORDER BY name")
    cites = _resolve_citations(h)
    # cites → {kind: [{id,label}]} 供表单预填多选器
    cite_pf = {
        "source": [{"id": s["id"], "label": f"[T{s['quality_tier']}] {s['title']}"} for s in cites["sources"]],
        "news": [{"id": n["id"], "label": n["title"]} for n in cites["news"]],
        "voice": [{"id": v["id"], "label": f"{v['leader_name']}:{(v['content_text'] or '')[:40]}"} for v in cites["voices"]],
        "event": [{"id": e["id"], "label": e["title"]} for e in cites["events"]],
        "company": [{"id": c["id"], "label": c["name"]} for c in
                    (query_one("SELECT id,name FROM company WHERE id=?", (cid,)) for cid in h["related_company_ids_list"]) if c],
    }
    prefill = {
        "mode": "edit", "id": h["id"],
        "h": {k: h.get(k) for k in ("id", "researcher_id", "title", "hypothesis_text", "thesis_type",
                                    "status", "conviction_level", "horizon_months", "is_draft")},
        "industry_ids": h["related_industry_ids_list"],
        "signals": [{"id": s["id"], "signal_type": s["signal_type"], "description": s["description"],
                     "observation_target": s.get("observation_target"), "kw": s.get("kw_list", [])} for s in signals],
        "trades": [{"trade_id": tr["id"], "trade_scenario": tr["trade_scenario"], "direction": tr["direction"],
                    "target_description": tr["target_description"],
                    "industry_ids": _as_id_list(tr.get("target_industry_ids")),
                    "company_ids": _as_id_list(tr.get("target_company_ids")),
                    "position_sizing": tr.get("position_sizing"), "entry_trigger": tr.get("entry_trigger"),
                    "exit_trigger": tr.get("exit_trigger"), "status": tr.get("status")} for tr in trades],
        "cites": cite_pf,
    }
    return render_template("hypothesis/form.html", mode="edit", h=h, signals=signals, trades=trades,
                           researchers=researchers, boards=boards, companies=companies,
                           cites=cites, prefill=prefill)


def _resolve_or_create_researcher(conn, rid_raw, name_raw):
    """数字 rid → 直接用;否则 sentinel(__other__/__intern__)+ 手填姓名 → 按名 upsert researcher。
    返回 (rid, err)。手填姓名按用户输入存(name);类别(其他研究员/实习生)存 focus_summary,
    不写任何敏感个人归属词。不破坏现有 researcher 关联(仅新增/复用同名)。"""
    try:
        return int(rid_raw), None
    except (TypeError, ValueError):
        pass
    name = (name_raw or "").strip()
    if not name:
        return None, "请选择研究员,或选『其他研究员 / 实习生』并填写姓名"
    cat = "实习生" if str(rid_raw) == "__intern__" else "其他研究员"
    row = conn.execute("SELECT id FROM researcher WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"], None
    if SHARED_IDENTITY_ROUTE.backend is DataBackend.POSTGRESQL_PRODUCTION:
        return None, (
            "PostgreSQL shared_identity 已成为唯一身份写入端；"
            "请先通过独立研究员创建接口建档，再提交假说。"
        )
    try:
        assert_sqlite_write_allowed(RUNTIME_LAYOUT.data_root, "shared_identity")
    except LocalAuthorityFenceError as exc:
        return None, str(exc)
    cur = conn.execute(
        "INSERT INTO researcher(name, display_name, focus_summary, is_active) VALUES(?,?,?,1)",
        (name, name, cat))
    return cur.lastrowid, None


# ── API:创建假说( 反 slop 校验)──────────────────────
@app.route("/api/hypothesis", methods=["POST"])
def api_hypothesis_create():
    d = _note_payload()
    is_draft = 1 if str(d.get("is_draft")) in ("1", "true", "True") else 0
    rid_raw = d.get("researcher_id")
    rname = d.get("researcher_name")
    title = (d.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "标题必填"}), 400
    text = (d.get("hypothesis_text") or "").strip()
    ttype = (d.get("thesis_type") or "").strip()
    conv = d.get("conviction_level")
    try:
        conv = int(conv) if conv not in (None, "") else None
    except Exception:
        conv = None
    # 持有周期:分类标签(周度/半月/月度/季度/半年/年度);兼容历史数字
    horizon = (str(d.get("horizon_months")).strip() if d.get("horizon_months") not in (None, "") else None)
    signals = d.get("signals") or []
    trades = d.get("trades") or []
    ind_ids = _as_id_list(d.get("related_industry_ids"))
    comp_ids = _as_id_list(d.get("related_company_ids"))
    cite = {
        "source": _as_id_list(d.get("cite_source_ids")),
        "news": _as_id_list(d.get("cite_news_ids")),
        "voice": _as_id_list(d.get("cite_voice_ids")),
        "event": _as_id_list(d.get("cite_event_ids")),
    }

    conn = get_domain_write_db("investment_hypotheses", "hypothesis_create")
    try:
        # 研究员:数字 id 须存在;『其他研究员 / 实习生』+ 手填姓名 → 按名 upsert(不破坏现有关联)
        rid, rerr = _resolve_or_create_researcher(conn, rid_raw, rname)
        if rerr:
            return jsonify({"ok": False, "error": rerr}), 400
        if not conn.execute("SELECT 1 FROM researcher WHERE id=?", (rid,)).fetchone():
            return jsonify({"ok": False, "error": f"researcher id={rid} 不存在"}), 400

        # 引用 id dangling 校验( 任何模式都查,绝不入库 dangling)
        dangling = {}
        for kind, table in (("source", "source"), ("news", "news_item"),
                            ("voice", "voice_post"), ("event", "event")):
            bad = _check_dangling(conn, table, cite[kind])
            if bad:
                dangling[kind] = bad
        bad_ind = _check_dangling(conn, "industry", ind_ids)
        bad_comp = _check_dangling(conn, "company", comp_ids)
        if bad_ind:
            dangling["industry"] = bad_ind
        if bad_comp:
            dangling["company"] = bad_comp
        if dangling:
            return jsonify({"ok": False, "error": "引用 id 在 db 中不存在(dangling)", "dangling": dangling}), 400

        # 正式提交(非草稿)硬校验
        if not is_draft:
            if not text:
                return jsonify({"ok": False, "error": "假说陈述必填(正式提交)"}), 400
            if ttype not in THESIS_TYPES:
                return jsonify({"ok": False, "error": f"方向须为 {THESIS_TYPES}"}), 400
            if conv is not None and not (1 <= conv <= 5):
                return jsonify({"ok": False, "error": "信心须 1-5"}), 400
            n_fals = sum(1 for s in signals if (s.get("signal_type") == "falsification"
                         and (s.get("description") or "").strip()))
            if n_fals < 1:
                return jsonify({"ok": False, "error": "至少 1 个证伪条件(falsification signal)"}), 400
            # 交易方案改为选填(正向/证伪后反向均不强制)
        else:
            # 草稿:仅 researcher + title;thesis_type 缺省 neutral 占位
            if ttype not in THESIS_TYPES:
                ttype = "neutral"
            if not text:
                text = ""

        now = datetime.now().isoformat(timespec="seconds")
        cur = conn.execute(
            """INSERT INTO hypothesis
               (researcher_id, title, hypothesis_text, thesis_type, status, conviction_level,
                is_draft, related_industry_ids, related_company_ids, horizon_months,
                cite_source_ids, cite_news_ids, cite_voice_ids, cite_event_ids, last_updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, title, text, ttype, "active", conv, is_draft,
             _dump(ind_ids), _dump(comp_ids), horizon,
             _dump(cite["source"]), _dump(cite["news"]), _dump(cite["voice"]), _dump(cite["event"]), now))
        hid = cur.lastrowid

        for i, s in enumerate(signals):
            stype = (s.get("signal_type") or "").strip()
            sdesc = (s.get("description") or "").strip()
            if stype not in ("falsification", "confirmation", "monitor") or not sdesc:
                continue
            conn.execute(
                """INSERT INTO hypothesis_monitoring_signal
                   (hypothesis_id, signal_type, description, observation_target,
                    ai_check_keywords, display_order)
                   VALUES(?,?,?,?,?,?)""",
                (hid, stype, sdesc, (s.get("observation_target") or "").strip() or None,
                 _dump(_kw_list(s.get("ai_check_keywords"))), i))

        for i, tr in enumerate(trades):
            scen = (tr.get("trade_scenario") or "").strip()
            tdesc = (tr.get("target_description") or "").strip()
            direction = (tr.get("direction") or "").strip()
            if scen not in ("primary", "falsification_reverse") or not tdesc:
                continue
            if direction not in ("long", "short", "neutral", "pair"):
                direction = "neutral"
            t_ind = _check_dangling(conn, "industry", _as_id_list(tr.get("target_industry_ids")))
            t_comp = _check_dangling(conn, "company", _as_id_list(tr.get("target_company_ids")))
            if t_ind or t_comp:
                conn.rollback()
                return jsonify({"ok": False, "error": "交易标的 tag id dangling",
                                "dangling": {"industry": t_ind, "company": t_comp}}), 400
            conn.execute(
                """INSERT INTO hypothesis_trade
                   (hypothesis_id, trade_scenario, direction, target_industry_ids,
                    target_company_ids, target_description, position_sizing, entry_trigger,
                    exit_trigger, display_order)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (hid, scen, direction, _dump(_as_id_list(tr.get("target_industry_ids"))),
                 _dump(_as_id_list(tr.get("target_company_ids"))), tdesc,
                 (tr.get("position_sizing") or "").strip() or None,
                 (tr.get("entry_trigger") or "").strip() or None,
                 (tr.get("exit_trigger") or "").strip() or None, i))

        _log_update(conn, hid, rid, "create",
                    note=("保存草稿" if is_draft else "创建假说"),
                    snap_status="active", snap_conv=conv)
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "hypothesis_id": hid, "is_draft": is_draft})


# ── API:编辑假说核心字段(版本化:append update + UPDATE)──
@app.route("/api/hypothesis/<int:hid>/edit", methods=["POST"])
def api_hypothesis_edit(hid: int):
    d = _note_payload()
    conn = get_domain_write_db("investment_hypotheses", "hypothesis_edit")
    try:
        old = conn.execute("SELECT * FROM hypothesis WHERE id=?", (hid,)).fetchone()
        if not old:
            return jsonify({"ok": False, "error": "假说不存在"}), 404
        old = dict(old)
        by = d.get("updated_by") or old["researcher_id"]
        try:
            by = int(by)
        except Exception:
            by = old["researcher_id"]
        # 允许编辑的字段
        new_title = (d.get("title") or old["title"]).strip()
        new_text = d.get("hypothesis_text")
        new_text = new_text.strip() if new_text is not None else old["hypothesis_text"]
        new_type = (d.get("thesis_type") or old["thesis_type"]).strip()
        if new_type not in THESIS_TYPES:
            new_type = old["thesis_type"]
        new_status = (d.get("status") or old["status"]).strip()
        if new_status not in HYP_STATUSES:
            new_status = old["status"]
        new_conv = d.get("conviction_level")
        try:
            new_conv = int(new_conv) if new_conv not in (None, "") else old["conviction_level"]
        except Exception:
            new_conv = old["conviction_level"]

        # 引用 dangling 校验(若提交了 cite)
        cite_cols = {}
        for key, col, table in (("cite_source_ids", "cite_source_ids", "source"),
                                ("cite_news_ids", "cite_news_ids", "news_item"),
                                ("cite_voice_ids", "cite_voice_ids", "voice_post"),
                                ("cite_event_ids", "cite_event_ids", "event")):
            if key in d:
                ids = _as_id_list(d.get(key))
                bad = _check_dangling(conn, table, ids)
                if bad:
                    return jsonify({"ok": False, "error": f"{key} dangling", "dangling": bad}), 400
                cite_cols[col] = _dump(ids)
        if "related_industry_ids" in d:
            ids = _as_id_list(d.get("related_industry_ids"))
            bad = _check_dangling(conn, "industry", ids)
            if bad:
                return jsonify({"ok": False, "error": "related_industry_ids dangling", "dangling": bad}), 400
            cite_cols["related_industry_ids"] = _dump(ids)
        if "related_company_ids" in d:
            ids = _as_id_list(d.get("related_company_ids"))
            bad = _check_dangling(conn, "company", ids)
            if bad:
                return jsonify({"ok": False, "error": "related_company_ids dangling", "dangling": bad}), 400
            cite_cols["related_company_ids"] = _dump(ids)

        # 判定 update_type + 快照旧值(append-only)
        if new_status != old["status"]:
            utype = "status_change"
        elif new_text != old["hypothesis_text"]:
            utype = "edit_text"
        elif cite_cols:
            utype = "cite_add"
        else:
            utype = "edit_text"
        _log_update(conn, hid, by, utype,
                    note=(d.get("update_note") or "").strip() or None,
                    snap_status=old["status"], snap_text=old["hypothesis_text"],
                    snap_conv=old["conviction_level"])

        now = datetime.now().isoformat(timespec="seconds")
        sets = ["title=?", "hypothesis_text=?", "thesis_type=?", "status=?",
                "conviction_level=?", "last_updated_at=?"]
        vals: List[Any] = [new_title, new_text, new_type, new_status, new_conv, now]
        if new_status == "falsified" and old["status"] != "falsified":
            sets.append("falsified_at=?"); vals.append(now)
        if new_status == "confirmed" and old["status"] != "confirmed":
            sets.append("confirmed_at=?"); vals.append(now)
        if str(d.get("is_draft")) in ("0", "false", "False") and old.get("is_draft"):
            sets.append("is_draft=0")
        for col, jv in cite_cols.items():
            sets.append(f"{col}=?"); vals.append(jv)
        if "horizon_months" in d:  # 持有周期(分类标签)
            sets.append("horizon_months=?")
            vals.append(str(d.get("horizon_months")).strip() or None if d.get("horizon_months") not in (None, "") else None)
        vals.append(hid)
        conn.execute(f"UPDATE hypothesis SET {', '.join(sets)} WHERE id=?", tuple(vals))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "hypothesis_id": hid})


# ── API:添加监控信号 ────────────────────────────────────
@app.route("/api/hypothesis/<int:hid>/signal", methods=["POST"])
def api_hypothesis_signal_add(hid: int):
    d = _note_payload()
    stype = (d.get("signal_type") or "").strip()
    desc = (d.get("description") or "").strip()
    if stype not in ("falsification", "confirmation", "monitor"):
        return jsonify({"ok": False, "error": "signal_type 非法"}), 400
    if not desc:
        return jsonify({"ok": False, "error": "信号描述必填"}), 400
    conn = get_domain_write_db("investment_hypotheses", "hypothesis_signal_add")
    try:
        h = conn.execute("SELECT researcher_id FROM hypothesis WHERE id=?", (hid,)).fetchone()
        if not h:
            return jsonify({"ok": False, "error": "假说不存在"}), 404
        nmax = conn.execute("SELECT COALESCE(MAX(display_order),-1) FROM hypothesis_monitoring_signal WHERE hypothesis_id=?", (hid,)).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO hypothesis_monitoring_signal
               (hypothesis_id, signal_type, description, observation_target, ai_check_keywords, display_order)
               VALUES(?,?,?,?,?,?)""",
            (hid, stype, desc, (d.get("observation_target") or "").strip() or None,
             _dump(_kw_list(d.get("ai_check_keywords"))), nmax + 1))
        _log_update(conn, hid, h["researcher_id"], "signal_update", note=f"添加监控信号:{desc[:40]}")
        conn.execute("UPDATE hypothesis SET last_updated_at=? WHERE id=?",
                     (datetime.now().isoformat(timespec="seconds"), hid))
        conn.commit()
        return jsonify({"ok": True, "signal_id": cur.lastrowid})
    finally:
        conn.close()


# ── API:删除监控信号(修红叉删不掉:校验归属 + 写 log,不静默删)──
@app.route("/api/hypothesis/<int:hid>/signal/<int:sid>/delete", methods=["POST"])
def api_hypothesis_signal_delete(hid: int, sid: int):
    conn = get_domain_write_db("investment_hypotheses", "hypothesis_signal_delete")
    try:
        h = conn.execute("SELECT researcher_id FROM hypothesis WHERE id=?", (hid,)).fetchone()
        if not h:
            return jsonify({"ok": False, "error": "假说不存在"}), 404
        row = conn.execute("SELECT description FROM hypothesis_monitoring_signal WHERE id=? AND hypothesis_id=?",
                           (sid, hid)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "监控信号不存在"}), 404
        conn.execute("DELETE FROM hypothesis_monitoring_signal WHERE id=? AND hypothesis_id=?", (sid, hid))
        _log_update(conn, hid, h["researcher_id"], "signal_update",
                    note=f"删除监控信号:{(row['description'] or '')[:40]}")
        conn.execute("UPDATE hypothesis SET last_updated_at=? WHERE id=?",
                     (datetime.now().isoformat(timespec="seconds"), hid))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── API:更新信号状态(研究员手判, 非 AI 自动)────────
@app.route("/api/hypothesis/<int:hid>/signal/<int:sid>/check", methods=["POST"])
def api_hypothesis_signal_check(hid: int, sid: int):
    d = _note_payload()
    st = (d.get("current_status") or "").strip()
    if st not in ("not_triggered", "partially_triggered", "triggered", "contradicted"):
        return jsonify({"ok": False, "error": "current_status 非法"}), 400
    conn = get_domain_write_db("investment_hypotheses", "hypothesis_signal_check")
    try:
        sig = conn.execute("SELECT * FROM hypothesis_monitoring_signal WHERE id=? AND hypothesis_id=?", (sid, hid)).fetchone()
        if not sig:
            return jsonify({"ok": False, "error": "信号不存在"}), 404
        h = conn.execute("SELECT researcher_id FROM hypothesis WHERE id=?", (hid,)).fetchone()
        by = d.get("updated_by") or h["researcher_id"]
        try:
            by = int(by)
        except Exception:
            by = h["researcher_id"]
        now = datetime.now().isoformat(timespec="seconds")
        note = (d.get("last_check_note") or "").strip() or None
        conn.execute(
            "UPDATE hypothesis_monitoring_signal SET current_status=?, last_check_at=?, last_check_note=?, updated_at=? WHERE id=?",
            (st, now, note, now, sid))
        _log_update(conn, hid, by, "signal_update",
                    note=f"信号「{sig['description'][:30]}」状态 → {hl(st)}" + (f":{note}" if note else ""))
        conn.execute("UPDATE hypothesis SET last_updated_at=? WHERE id=?", (now, hid))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── API:添加 / 更新交易方案 ─────────────────────────────
@app.route("/api/hypothesis/<int:hid>/trade", methods=["POST"])
def api_hypothesis_trade(hid: int):
    d = _note_payload()
    scen = (d.get("trade_scenario") or "").strip()
    direction = (d.get("direction") or "").strip()
    tdesc = (d.get("target_description") or "").strip()
    if scen not in ("primary", "falsification_reverse"):
        return jsonify({"ok": False, "error": "trade_scenario 非法"}), 400
    if direction not in ("long", "short", "neutral", "pair"):
        return jsonify({"ok": False, "error": "direction 非法"}), 400
    if not tdesc:
        return jsonify({"ok": False, "error": "标的描述必填"}), 400
    new_status = (d.get("status") or "proposed").strip()
    if new_status not in ("proposed", "active", "closed_profit", "closed_loss", "abandoned"):
        new_status = "proposed"
    conn = get_domain_write_db("investment_hypotheses", "hypothesis_trade_upsert")
    try:
        h = conn.execute("SELECT researcher_id FROM hypothesis WHERE id=?", (hid,)).fetchone()
        if not h:
            return jsonify({"ok": False, "error": "假说不存在"}), 404
        t_ind = _as_id_list(d.get("target_industry_ids"))
        t_comp = _as_id_list(d.get("target_company_ids"))
        bad = _check_dangling(conn, "industry", t_ind) + _check_dangling(conn, "company", t_comp)
        if bad:
            return jsonify({"ok": False, "error": "交易标的 tag dangling", "dangling": bad}), 400
        tid = d.get("trade_id")
        if tid and str(tid).isdigit() and conn.execute("SELECT 1 FROM hypothesis_trade WHERE id=? AND hypothesis_id=?", (int(tid), hid)).fetchone():
            conn.execute(
                """UPDATE hypothesis_trade SET trade_scenario=?, direction=?, target_industry_ids=?,
                   target_company_ids=?, target_description=?, position_sizing=?, entry_trigger=?,
                   exit_trigger=?, status=?, updated_at=datetime('now','localtime') WHERE id=?""",
                (scen, direction, _dump(t_ind), _dump(t_comp), tdesc,
                 (d.get("position_sizing") or "").strip() or None,
                 (d.get("entry_trigger") or "").strip() or None,
                 (d.get("exit_trigger") or "").strip() or None, new_status, int(tid)))
            trade_id = int(tid)
        else:
            cur = conn.execute(
                """INSERT INTO hypothesis_trade
                   (hypothesis_id, trade_scenario, direction, target_industry_ids, target_company_ids,
                    target_description, position_sizing, entry_trigger, exit_trigger, status)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (hid, scen, direction, _dump(t_ind), _dump(t_comp), tdesc,
                 (d.get("position_sizing") or "").strip() or None,
                 (d.get("entry_trigger") or "").strip() or None,
                 (d.get("exit_trigger") or "").strip() or None, new_status))
            trade_id = cur.lastrowid
        _log_update(conn, hid, h["researcher_id"], "trade_update",
                    note=f"{hl(scen)} 交易方案更新:{tdesc[:40]}")
        conn.execute("UPDATE hypothesis SET last_updated_at=? WHERE id=?",
                     (datetime.now().isoformat(timespec="seconds"), hid))
        conn.commit()
        return jsonify({"ok": True, "trade_id": trade_id})
    finally:
        conn.close()


# ── API:删除单条交易方案(修重复卡 bug:可单独删除,不静默删真数据)──
@app.route("/api/hypothesis/<int:hid>/trade/<int:tid>/delete", methods=["POST"])
def api_hypothesis_trade_delete(hid: int, tid: int):
    conn = get_domain_write_db("investment_hypotheses", "hypothesis_trade_delete")
    try:
        h = conn.execute("SELECT researcher_id FROM hypothesis WHERE id=?", (hid,)).fetchone()
        if not h:
            return jsonify({"ok": False, "error": "假说不存在"}), 404
        row = conn.execute("SELECT target_description FROM hypothesis_trade WHERE id=? AND hypothesis_id=?",
                           (tid, hid)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "交易方案不存在"}), 404
        conn.execute("DELETE FROM hypothesis_trade WHERE id=? AND hypothesis_id=?", (tid, hid))
        _log_update(conn, hid, h["researcher_id"], "trade_update",
                    note=f"删除交易方案:{(row['target_description'] or '')[:40]}")
        conn.execute("UPDATE hypothesis SET last_updated_at=? WHERE id=?",
                     (datetime.now().isoformat(timespec="seconds"), hid))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── API:AI 辅助监控( 只标红推送,不判断"已触发",不给买卖建议)──
@app.route("/api/hypothesis/<int:hid>/ai-monitor")
def api_hypothesis_ai_monitor(hid: int):
    try:
        days = int(request.args.get("days", 7))
    except Exception:
        days = 7
    days = max(1, min(days, 90))
    sigs = query_all("SELECT id, description, ai_check_keywords FROM hypothesis_monitoring_signal WHERE hypothesis_id=?", (hid,))
    kw_index: List[tuple] = []  # (keyword, signal_id, signal_desc)
    for s in sigs:
        for k in _kw_list(s.get("ai_check_keywords")):
            kw_index.append((k, s["id"], s["description"]))
    if not kw_index:
        return jsonify({"ok": True, "hits": [],
                        "note": "该假说尚无 AI 检测关键词;研究员可在信号里补关键词。",
                        "disclaimer": " 仅辅助,请研究员人工判断 signal 是否真触发"})
    from datetime import date as _d, timedelta as _td
    since = (_d.today() - _td(days=days)).isoformat()
    hits = []
    news = query_all(
        "SELECT id, title, url, source_publisher, content_text, publish_date, fetch_timestamp "
        "FROM news_item WHERE COALESCE(publish_date, fetch_timestamp) >= ? "
        "ORDER BY COALESCE(publish_date, fetch_timestamp) DESC LIMIT 400", (since,))
    for n in news:
        hay = (n.get("title") or "") + " " + (n.get("content_text") or "") + " " + (n.get("title_zh") or "")
        matched = sorted({k for k, sid, sd in kw_index if k and k in hay})
        if matched:
            hits.append({"type": "news", "id": n["id"], "title": n["title"], "url": n["url"],
                         "when": (n.get("publish_date") or (n.get("fetch_timestamp") or "")[:10]),
                         "publisher": n.get("source_publisher"), "matched": matched})
    voices = query_all(
        "SELECT vp.id, vp.content_text, vp.post_url, vp.posted_at, ol.name AS leader_name "
        "FROM voice_post vp JOIN opinion_leader ol ON ol.id=vp.leader_id "
        "WHERE COALESCE(vp.posted_at, vp.fetch_timestamp) >= ? ORDER BY vp.posted_at DESC LIMIT 200", (since,))
    for v in voices:
        hay = v.get("content_text") or ""
        matched = sorted({k for k, sid, sd in kw_index if k and k in hay})
        if matched:
            hits.append({"type": "voice", "id": v["id"], "title": (v.get("content_text") or "")[:60],
                         "url": v.get("post_url"), "when": (v.get("posted_at") or "")[:10],
                         "leader": v.get("leader_name"), "matched": matched})
    return jsonify({"ok": True, "hits": hits, "scanned_days": days,
                    "disclaimer": " 仅辅助,请研究员人工判断 signal 是否真触发;系统不给买卖建议。"})


# ── API:加新研究员(预留;名单由 user 手动扩,CC 不自加)──
@app.route("/api/researcher", methods=["POST"])
def api_researcher_create():
    d = _note_payload()
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name 必填"}), 400
    ind_ids = _as_id_list(d.get("focus_industries"))
    if SHARED_IDENTITY_ROUTE.backend is DataBackend.POSTGRESQL_PRODUCTION:
        try:
            principal = require_user_content_principal(
                app, request, permission="shared_identity:write", csrf=True
            )
            operation_id = (request.headers.get("X-Idempotency-Key") or "").strip()
            if not operation_id:
                return jsonify(
                    {"ok": False, "error": "X-Idempotency-Key 必填"}
                ), 400
            if SHARED_IDENTITY_REPOSITORY is None:
                raise SharedIdentityWriterFenced(
                    "PostgreSQL shared identity repository is unavailable"
                )
            result = SHARED_IDENTITY_REPOSITORY.create_researcher(
                name=name,
                display_name=(d.get("display_name") or name).strip(),
                focus_summary=(d.get("focus_summary") or "").strip() or None,
                focus_industries=ind_ids,
                bio=(d.get("bio") or "").strip() or None,
                idempotency_key=operation_id,
                actor=principal.subject,
            )
            return jsonify({"ok": True, **result})
        except SharedIdentityConflict as exc:
            return jsonify(
                {"ok": False, "error": str(exc), "code": "identity_conflict"}
            ), 409
        except (SharedIdentityWriterFenced, UserContentSecurityError) as exc:
            if isinstance(exc, UserContentSecurityError):
                return _user_content_error(exc)
            return jsonify(
                {"ok": False, "error": str(exc), "code": "writer_fenced"}
            ), 503
        except SharedIdentityError as exc:
            return jsonify(
                {"ok": False, "error": str(exc), "code": "identity_write_failed"}
            ), 500
    conn = get_db()
    try:
        assert_sqlite_write_allowed(RUNTIME_LAYOUT.data_root, "shared_identity")
        bad = _check_dangling(conn, "industry", ind_ids)
        if bad:
            return jsonify({"ok": False, "error": "focus_industries dangling", "dangling": bad}), 400
        if conn.execute("SELECT 1 FROM researcher WHERE name=?", (name,)).fetchone():
            return jsonify({"ok": False, "error": f"研究员「{name}」已存在"}), 400
        cur = conn.execute(
            "INSERT INTO researcher(name, display_name, focus_summary, focus_industries, bio) VALUES(?,?,?,?,?)",
            (name, (d.get("display_name") or name).strip(),
             (d.get("focus_summary") or "").strip() or None, _dump(ind_ids),
             (d.get("bio") or "").strip() or None))
        conn.commit()
        return jsonify({"ok": True, "researcher_id": cur.lastrowid})
    except LocalAuthorityFenceError as exc:
        return jsonify(
            {"ok": False, "error": str(exc), "code": "writer_fenced"}
        ), 503
    finally:
        conn.close()


# ── API:引用材料搜索(假说表单的 source/news/voice/event 多选器)──
@app.route("/api/hyp/search")
def api_hyp_search():
    kind = (request.args.get("kind") or "").strip()
    q = (request.args.get("q") or "").strip()
    like = f"%{q}%"
    out = []
    if kind == "source":
        rows = query_all("SELECT id, title, quality_tier FROM source WHERE title LIKE ? "
                         "ORDER BY quality_tier, id DESC LIMIT 25", (like,))
        out = [{"id": r["id"], "label": f"[T{r['quality_tier']}] {r['title']}"} for r in rows]
    elif kind == "news":
        rows = query_all("SELECT id, title, source_publisher FROM news_item WHERE title LIKE ? OR title_zh LIKE ? "
                         "ORDER BY COALESCE(publish_date,fetch_timestamp) DESC LIMIT 25", (like, like))
        out = [{"id": r["id"], "label": f"{r['title']} · {r['source_publisher'] or ''}"} for r in rows]
    elif kind == "voice":
        rows = query_all("SELECT vp.id, vp.content_text, ol.name AS leader FROM voice_post vp "
                         "JOIN opinion_leader ol ON ol.id=vp.leader_id WHERE vp.content_text LIKE ? "
                         "ORDER BY vp.posted_at DESC LIMIT 25", (like,))
        out = [{"id": r["id"], "label": f"{r['leader']}:{(r['content_text'] or '')[:48]}"} for r in rows]
    elif kind == "event":
        rows = query_all("SELECT id, title, scheduled_date FROM event WHERE title LIKE ? "
                         "ORDER BY scheduled_date DESC LIMIT 25", (like,))
        out = [{"id": r["id"], "label": f"{r['title']} · {r['scheduled_date'] or ''}"} for r in rows]
    elif kind == "company":
        rows = query_all("SELECT id, name, ticker FROM company WHERE name LIKE ? OR ticker LIKE ? "
                         "ORDER BY name LIMIT 25", (like, like))
        out = [{"id": r["id"], "label": r["name"] + (f" ({r['ticker']})" if r["ticker"] else "")} for r in rows]
    else:
        return jsonify({"ok": False, "error": "kind 须为 source/news/voice/event/company"}), 400
    return jsonify({"ok": True, "results": out})


# ── 路由:健康检查(烟测用)──────────────────────────
@app.route("/api/health")
def api_health():
    try:
        conn = get_db()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()]
        battery_row = conn.execute(
            "SELECT id FROM industry WHERE name = ?",
            ("锂电池",),
        ).fetchone()
        conn.close()
        manifest_path = ROOT / "BROADCAST_MANIFEST.json"
        release_version = None
        release_created_at = None
        manifest_sha256 = None
        if manifest_path.is_file():
            manifest_bytes = manifest_path.read_bytes()
            manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
            try:
                release_manifest = json.loads(manifest_bytes)
                release_version = release_manifest.get("version")
                release_created_at = release_manifest.get("created_at")
            except Exception:
                release_version = "manifest_unreadable"
        app_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        active_routes = {rule.rule for rule in app.url_map.iter_rules()}
        payload = {
            "ok": True,
            "db_path": str(DB_PATH) if not app.config.get("HONGHU_READ_ONLY_CANDIDATE") else None,
            "tables": tables,
            "table_count": len(tables),
            "release_version": release_version,
            "release_created_at": release_created_at,
            "release_manifest_sha256": manifest_sha256,
            "app_sha256": app_sha256,
            "active_features": {
                "battery_industry_id": int(battery_row[0]) if battery_row else None,
                "battery_model_exists": (
                    ROOT
                    / "config"
                    / "battery_calculator_models"
                    / "battery_calculator_model_v1.json"
                ).is_file(),
                "battery_calculator_route": (
                    "/tools/battery-calculator" in active_routes
                ),
                "battery_comparison_route": (
                    "/industry/lithium-battery/comparison" in active_routes
                ),
            },
            "research_content_contract": {
                "contract_count": int(
                    os.environ.get("HONGHU_RESEARCH_CONTENT_CONTRACT_COUNT") or 0
                ),
                "file_count": int(
                    os.environ.get("HONGHU_RESEARCH_CONTENT_FILE_COUNT") or 0
                ),
                "sha256": (
                    os.environ.get("HONGHU_RESEARCH_CONTENT_CONTRACT_SHA256")
                    or None
                ),
            },
            "time": datetime.now().isoformat(timespec="seconds"),
            "viewer_mode": (
                "readonly_candidate"
                if app.config.get("HONGHU_READ_ONLY_CANDIDATE")
                else (
                    "production_hybrid"
                    if os.environ.get("HONGHU_VIEWER_MODE")
                    in {"production_postgresql", "production_hybrid"}
                    else "legacy_live"
                )
            ),
            "backend_matrix": (
                AUTHORITY_MATRIX.health_payload()
                if AUTHORITY_MATRIX is not None
                else {
                    USER_CONTENT_ROUTE.cutover_unit: {
                        "state": USER_CONTENT_ROUTE.authority_state.value,
                        "authoritative_backend": USER_CONTENT_ROUTE.backend.value,
                        "sqlite_writer_enabled": USER_CONTENT_ROUTE.sqlite_writer_enabled,
                    },
                    SHARED_IDENTITY_ROUTE.cutover_unit: {
                        "state": SHARED_IDENTITY_ROUTE.authority_state.value,
                        "authoritative_backend": SHARED_IDENTITY_ROUTE.backend.value,
                        "sqlite_writer_enabled": SHARED_IDENTITY_ROUTE.sqlite_writer_enabled,
                    },
                }
            ),
            "user_content": {
                "cutover_unit": USER_CONTENT_ROUTE.cutover_unit,
                "authority_state": USER_CONTENT_ROUTE.authority_state.value,
                "backend": USER_CONTENT_ROUTE.backend.value,
                "sqlite_writer_enabled": USER_CONTENT_ROUTE.sqlite_writer_enabled,
                "production_postgresql_enabled": (
                    USER_CONTENT_ROUTE.production_postgresql_enabled
                ),
                "security_ready": bool(
                    app.config.get("HONGHU_USER_CONTENT_SECURITY_READY")
                ),
                "https_required": bool(
                    current_user_content_security_settings(app).require_https
                ),
            },
            "shared_identity": {
                "cutover_unit": SHARED_IDENTITY_ROUTE.cutover_unit,
                "authority_state": SHARED_IDENTITY_ROUTE.authority_state.value,
                "backend": SHARED_IDENTITY_ROUTE.backend.value,
                "sqlite_writer_enabled": SHARED_IDENTITY_ROUTE.sqlite_writer_enabled,
                "production_postgresql_enabled": (
                    SHARED_IDENTITY_ROUTE.production_postgresql_enabled
                ),
                "read_cache_enabled": SHARED_IDENTITY_READ_CACHE is not None,
                "failure_policy": "fail_closed_no_sqlite_identity_fallback",
            },
        }
        if app.config.get("HONGHU_READ_ONLY_CANDIDATE"):
            deploy_root = os.environ.get("HONGHU_DEPLOY_ROOT")
            if deploy_root:
                from tools.release.manager import release_health_payload

                release_health = release_health_payload(
                    deploy_root,
                    data_root=RUNTIME_LAYOUT.data_root,
                )
                payload["ok"] = bool(payload["ok"] and release_health["ok"])
                payload["release"] = release_health["release"]
                payload["database_contract"] = release_health["database_contract"]
            payload["candidate_process"] = {
                "pid": os.getpid(),
                "launch_id": os.environ.get("HONGHU_CANDIDATE_LAUNCH_ID"),
                "python_version": ".".join(map(str, sys.version_info[:3])),
            }
        elif payload["viewer_mode"] in {"production_postgresql", "production_hybrid"}:
            exact_manifest = Path(
                os.environ.get("HONGHU_RELEASE_MANIFEST") or ""
            )
            payload["release"] = {
                "commit_sha": os.environ.get("HONGHU_RELEASE_COMMIT"),
                "manifest_sha256": (
                    hashlib.sha256(exact_manifest.read_bytes()).hexdigest()
                    if exact_manifest.is_file()
                    else None
                ),
            }
            payload["production_process"] = {
                "pid": os.getpid(),
                "launch_id": os.environ.get("HONGHU_PRODUCTION_LAUNCH_ID"),
                "python_version": ".".join(map(str, sys.version_info[:3])),
            }
        return jsonify(payload)
    except Exception:
        log.error(f"health error: {traceback.format_exc()}")
        return jsonify({"ok": False, "error": "db check failed"}), 500


# ── 错误页 ───────────────────────────────────────────
@app.errorhandler(404)
def err_404(e):
    return render_template("base.html", error=f"404: {e.description if hasattr(e, 'description') else e}"), 404


@app.errorhandler(500)
def err_500(e):
    log.error(f"500: {traceback.format_exc()}")
    return render_template("base.html", error="500: 服务器内部错误,见 cache/viewer_debug.log"), 500


# ════ 情绪+事件+代理+专题系统(独立 sentiment.db;research.db 只读 ATTACH;C1)════
def _spark_pts(vals, w=84, h=22, pad=2):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = pad + (w - 2 * pad) * i / (n - 1)
        y = h - pad - (h - 2 * pad) * (v - lo) / rng
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _candles(rows, w=560, h=170, pad=22):
    """情绪K线几何:rows=[{ts_hour,o,h,l,c,vol}] → 蜡烛绘制坐标。"""
    if not rows:
        return None
    vals = []
    for r in rows:
        vals += [r["o"], r["h"], r["l"], r["c"]]
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    n = len(rows)
    cw = (w - 2 * pad) / max(n, 1)

    def Y(v):
        return h - pad - (h - 2 * pad) * (v - lo) / rng
    cs = []
    for i, r in enumerate(rows):
        x = pad + cw * i + cw * 0.5
        up = (r["c"] or 0) >= (r["o"] or 0)
        cs.append({"x": round(x, 1), "bw": round(max(cw * 0.55, 2), 1),
                   "wy1": round(Y(r["h"]), 1), "wy2": round(Y(r["l"]), 1),
                   "by": round(Y(max(r["o"], r["c"])), 1),
                   "bh": round(max(abs(Y(r["o"]) - Y(r["c"])), 1.5), 1),
                   "up": up, "ts": (r["ts_hour"] or "")[5:]})
    return {"candles": cs, "w": w, "h": h, "lo": round(lo, 2), "hi": round(hi, 2)}


def _quant_fig(price, senti, freq):
    """T9/U1/U5:量化叠加图(Plotly figure dict)。价格蜡烛(主)+ 情绪方向线(副轴)+ 发帖量柱(底)。
    高对比深色;A股红涨绿跌;默认 x 轴对齐到【情绪有覆盖窗口】(不拿2h情绪去对60天价);x轴横排稀疏可读;
    tooltip 深底亮字;鼠标滚轮缩放 + 双击/工具栏还原(模板 config)。"""
    if not price and not senti:
        return None
    skey = "trade_date" if freq == "d" else "ts_hour"
    vkey = "post_count" if freq == "d" else "post_count_hour"
    sx = [r[skey] for r in senti]
    data = []
    if price:
        data.append({"type": "candlestick", "x": [r["ts"] for r in price],
                     "open": [r["o"] for r in price], "high": [r["h"] for r in price],
                     "low": [r["l"] for r in price], "close": [r["c"] for r in price],
                     "name": "股价", "yaxis": "y",
                     "increasing": {"line": {"color": "#ff5b52"}, "fillcolor": "#ff5b52"},
                     "decreasing": {"line": {"color": "#22c08a"}, "fillcolor": "#22c08a"}})
    data.append({"type": "scatter", "mode": "lines+markers", "x": sx,
                 "y": [r["sentiment_direction"] for r in senti], "name": "情绪方向(自算)",
                 "yaxis": "y2", "line": {"color": "#d59bff", "width": 2}, "connectgaps": False,
                 "marker": {"size": 5, "color": "#d59bff"}})
    data.append({"type": "bar", "x": sx, "y": [r[vkey] for r in senti], "name": "发帖量",
                 "yaxis": "y3", "marker": {"color": "rgba(110,170,255,.7)"}})
    # 高对比轴
    axis = dict(gridcolor="rgba(255,255,255,.10)", zerolinecolor="rgba(255,255,255,.20)",
                linecolor="rgba(255,255,255,.25)", color="#c9d6ea", tickfont={"size": 11, "color": "#c9d6ea"})
    tickfmt = "%m-%d" if freq == "d" else "%m-%d %H:%M"
    #  U5:默认显示情绪覆盖窗口(对齐);无情绪则显示全价格
    xr = None
    if sx:
        lo = sx[0]
        hi = max(sx[-1], price[-1]["ts"]) if price else sx[-1]
        xr = [lo, hi]
    #  V2:rangebreaks 屏蔽休市 → K线连续不离散(日线跳周末;小时线跳周末+夜间+午休 A股 09:30-11:30/13:00-15:00)
    if freq == "d":
        rbreaks = [{"bounds": ["sat", "mon"]}]
    else:
        rbreaks = [{"bounds": ["sat", "mon"]},
                   {"bounds": [15.5, 9.5], "pattern": "hour"},
                   {"bounds": [11.5, 13], "pattern": "hour"}]
    #  默认 autoscale:价格/发帖量/x 轴全部交给 Plotly 自动缩放(autorange),不预设区间。
    #   情绪方向轴 yaxis2 仍固定 [-1,1](有界方向分,需稳定参考系)。
    layout = {
        "height": 480, "margin": {"l": 54, "r": 18, "t": 12, "b": 52},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(255,255,255,.025)",
        "showlegend": True, "legend": {"orientation": "h", "y": 1.06, "x": 0,
                                       "font": {"color": "#dde7f6", "size": 12}},
        "hoverlabel": {"bgcolor": "#0e1830", "bordercolor": "#5a78b0",
                       "font": {"color": "#eaf2ff", "size": 12}},
        "xaxis": {**axis, "rangeslider": {"visible": False}, "type": "date",
                  "domain": [0, 1], "anchor": "y3", "tickformat": tickfmt, "tickangle": 0,
                  "nticks": 9, "showgrid": True, "rangebreaks": rbreaks, "autorange": True},
        "yaxis": {**axis, "domain": [0.50, 1.0], "title": {"text": "股价", "font": {"size": 12, "color": "#c9d6ea"}},
                  "autorange": True},
        "yaxis2": {**axis, "domain": [0.27, 0.48], "title": {"text": "情绪方向[-1,1]", "font": {"size": 12, "color": "#c9d6ea"}},
                   "range": [-1.05, 1.05], "dtick": 0.5, "zeroline": True, "fixedrange": True},
        "yaxis3": {**axis, "domain": [0.0, 0.24], "title": {"text": "发帖量", "font": {"size": 12, "color": "#c9d6ea"}},
                   "autorange": True},
        "hovermode": "x unified", "dragmode": "zoom",
    }
    return {"data": data, "layout": layout}


@app.route("/dynamic/sentiment")
def dynamic_sentiment():
    """散户情绪墙：活动量取最新观察，评分按与公司页一致的完成口径回退。"""
    research_names = {r["id"]: r for r in senti_all("SELECT id,name,ticker FROM company")}
    sentiment_names = {r["id"]: r for r in senti_all("SELECT id,name,ticker FROM senti_company")}
    redirect = {}
    if _senti_table_exists("company_id_redirect"):
        redirect = {r["old_company_id"]: r["canonical_company_id"] for r in senti_all(
            "SELECT old_company_id,canonical_company_id FROM company_id_redirect")}

    latest_activity: dict[int, dict] = {}
    summary_candidates: dict[int, list[dict]] = {}

    def _keep_latest(target: dict, cid: int, row: dict):
        key = _timeline_sort_key(str(row.get("key") or ""), row.get("timeline"))
        previous = target.get(cid)
        previous_key = _timeline_sort_key(
            str((previous or {}).get("key") or ""), (previous or {}).get("timeline")
        )
        if not previous or key >= previous_key:
            target[cid] = row

    def _add_candidate(source_cid: int, row: dict) -> None:
        cid = redirect.get(source_cid, source_cid)
        row["company_id"] = cid
        summary_candidates.setdefault(cid, []).append(row)
        _keep_latest(latest_activity, cid, row)

    # legacy 作为历史基线；V2 日线和窗口都进入候选，避免首个 V2 交易日尚未
    # 三窗齐全时，窗口里明明已有评分却从首页整批消失。
    spark_rows = senti_all(
        "SELECT company_id,retail_count AS volume FROM heat_volume_bucket ORDER BY bucket_start"
    )
    legacy_daily = senti_all("SELECT * FROM senti_retail_daily ORDER BY company_id, trade_date")
    heat_rows = senti_all("SELECT * FROM heat_volume_daily ORDER BY company_id, trade_date")
    heat_by_key = {(r["company_id"], r["trade_date"]): r for r in heat_rows}
    for row in legacy_daily:
        try:
            if datetime.strptime((row.get("trade_date") or "")[:10], "%Y-%m-%d").weekday() >= 5:
                continue
        except ValueError:
            continue
        source_cid = row["company_id"]
        heat = heat_by_key.get((source_cid, row.get("trade_date"))) or {}
        normalized = {
            **dict(row),
            "key": row.get("trade_date"),
            "timeline": f"{row.get('trade_date')}T23:59:00+08:00",
            "scored_count": row.get("valid_count") or 0,
            "raw_count": heat.get("retail_count") or 0,
            "net_weighted": row.get("net_sentiment_weighted"),
            "net_plain": (row.get("net_sentiment_plain")
                          if row.get("net_sentiment_plain") is not None
                          else row.get("net_sentiment")),
            "display_ready": bool(row.get("usable")),
            "score_label": f"{row.get('trade_date')} 日线",
            "score_badge": None if row.get("usable") else "低样本历史日线",
            "mode": "legacy_daily",
        }
        _add_candidate(source_cid, normalized)

    if _senti_table_exists("senti_retail_trading_daily"):
        daily_rows = senti_all(
            "SELECT * FROM senti_retail_trading_daily ORDER BY company_id, session_date"
        )
        for row in daily_rows:
            complete = bool(row.get("complete"))
            significant = bool(row.get("significant"))
            normalized = {
                **dict(row),
                "key": row.get("session_date"),
                "timeline": f"{row.get('session_date')}T23:59:00+08:00",
                "display_ready": bool(complete and significant),
                "score_label": f"{row.get('session_date')} 日线",
                "score_badge": (None if complete and significant else
                                "低样本日线" if complete else "当日汇总中"),
                "mode": "v2_daily",
            }
            _add_candidate(row["company_id"], normalized)

    if (_senti_table_exists("senti_retail_window")
            and _senti_table_exists("retail_window_ledger")):
        window_rows = senti_all(
            """SELECT w.*,l.session_date,l.slot,l.scheduled_for,
                      l.status AS window_status,l.source_status_json
               FROM senti_retail_window w JOIN retail_window_ledger l ON l.window_id=w.window_id
               ORDER BY l.scheduled_for,w.window_id,w.company_id"""
        )
        for row in window_rows:
            statuses = _json_or({}, row.get("source_status_json"))
            score_complete = (
                statuses.get("score") == "complete"
                if statuses else row.get("window_status") == "complete"
            )
            significant = bool(row.get("significant"))
            display_ready = bool(score_complete and significant)
            scheduled = str(row.get("scheduled_for") or "")
            session_date = str(row.get("session_date") or row.get("window_id") or "")[:10]
            slot_name = {"preopen": "盘前", "morning": "早盘", "afternoon": "午后"}.get(
                row.get("slot"), "交易窗口"
            )
            scheduled_time = scheduled[11:16] if len(scheduled) >= 16 else ""
            score_label = " ".join(part for part in (session_date, slot_name, scheduled_time) if part)
            if not score_complete:
                score_badge = "评分进行中"
            elif not significant:
                score_badge = "低样本窗口"
            elif row.get("window_status") != "complete":
                score_badge = "窗口评分完成 · 附加源补抓中"
            else:
                score_badge = None
            normalized = {
                **dict(row),
                "key": row.get("window_id"),
                "timeline": row.get("scheduled_for"),
                "display_ready": display_ready,
                "score_label": score_label,
                "score_badge": score_badge,
                "mode": "v2_window",
            }
            _add_candidate(row["company_id"], normalized)
            spark_rows.append({"company_id": row["company_id"],
                               "volume": row.get("raw_count") or 0})

    for candidates in summary_candidates.values():
        candidates.sort(key=lambda row: _timeline_sort_key(
            str(row.get("key") or ""), row.get("timeline")
        ))

    # 产业映射(research.db 只读;一家可多产业,取主营/最小 id 为主组)
    comp_ind: Dict[int, list] = {}
    for r in senti_all("""SELECT ci.company_id, i.id AS ind_id, i.name AS ind_name, ci.role
                          FROM company_industry ci JOIN industry i ON i.id=ci.industry_id"""):
        comp_ind.setdefault(r["company_id"], []).append((r["ind_id"], r["ind_name"], r["role"]))
    # 散户发帖量 spark；redirect 后不再泄露 #900xxx identity。
    spark: Dict[int, list] = {}
    for r in spark_rows:
        cid = redirect.get(r["company_id"], r["company_id"])
        spark.setdefault(cid, []).append(r.get("volume") or 0)
    rows = []
    for cid, activity in latest_activity.items():
        chosen = _latest_retail_summary_row(summary_candidates.get(cid, [])) or activity
        d = dict(activity)
        d["company_id"] = cid
        d["score_date"] = chosen.get("score_label")
        d["valid_count"] = chosen.get("scored_count") or 0
        d["net_sentiment_weighted"] = (chosen.get("net_weighted")
                                              if chosen.get("net_weighted") is not None
                                              else chosen.get("net_plain"))
        d["coverage"] = chosen.get("coverage")
        d["heat_total"] = activity.get("raw_count") or 0
        d["display_ready"] = bool(chosen.get("display_ready"))
        d["usable"] = bool(chosen.get("usable"))
        d["score_badge"] = chosen.get("score_badge")
        d["score_mode"] = chosen.get("mode")
        identity = research_names.get(cid) or sentiment_names.get(cid) or {}
        d["company_name"] = identity.get("name") or "名称待核验"
        d["ticker"] = identity.get("ticker") or d.get("ticker") or ""
        d["is_research_company"] = cid in research_names
        inds = sorted(comp_ind.get(cid, []), key=lambda x: (0 if (x[2] or "")[:2] in ("主营", "核心") else 1, x[0]))
        d["industries"] = [x[1] for x in inds]
        d["primary_ind"] = inds[0][1] if inds else "未分类"
        d["primary_ind_id"] = inds[0][0] if inds else 9999
        d["spark_pts"] = _spark_pts(spark.get(cid, [])[-30:])
        rows.append(d)
    rows.sort(key=lambda x: -(x["heat_total"] or 0))
    # 按产业分组(主组)
    groups: Dict[str, dict] = {}
    for d in rows:
        g = groups.setdefault(d["primary_ind"], {"name": d["primary_ind"], "ind_id": d["primary_ind_id"], "companies": []})
        g["companies"].append(d)
    group_list = sorted(groups.values(), key=lambda g: (g["ind_id"], g["name"]))
    kpi = {"covered": len(rows),
           "significant": sum(1 for r in rows if r["display_ready"]),
           "with_score": sum(1 for r in rows if r["net_sentiment_weighted"] is not None),
           "industries": len(group_list)}
    return render_template("sentiment.html", rows=rows, groups=group_list, kpi=kpi)


@app.route("/dynamic/monitor/<int:company_id>")
def sentiment_monitor(company_id):
    """单公司聚合监控页(学 net/pltr-monitor):情绪信号 + 事件时间线 + 基本面次要。"""
    co = query_one("SELECT * FROM company WHERE id=?", (company_id,))
    if not co:
        abort(404)
    profile = query_one("SELECT * FROM company_profile WHERE company_id=? LIMIT 1", (company_id,))
    senti = senti_all("SELECT * FROM senti_discussion_daily WHERE company_id=? ORDER BY trade_date DESC LIMIT 40", (company_id,))
    ind = senti_one("SELECT * FROM senti_indicator_daily WHERE company_id=? ORDER BY trade_date DESC LIMIT 1", (company_id,))
    ind_h = senti_one("SELECT * FROM senti_indicator_hourly WHERE company_id=? ORDER BY ts_hour DESC LIMIT 1", (company_id,))
    events = senti_all("SELECT * FROM event_item WHERE entity_type='company' AND entity_id=? ORDER BY published_at DESC LIMIT 30", (company_id,))
    sp = _spark_pts([r["post_count"] for r in reversed(senti)], w=240, h=54)
    # T9 量化叠加图:价格蜡烛(主)+ 情绪方向线(副轴)+ 发帖量柱(底);日线 & 小时线
    kd = senti_all("SELECT ts,o,h,l,c,vol FROM stock_kline WHERE company_id=? AND freq='d' ORDER BY ts", (company_id,))
    idd = senti_all("SELECT trade_date, post_count, sentiment_direction FROM senti_indicator_daily WHERE company_id=? ORDER BY trade_date", (company_id,))
    kh = senti_all("SELECT ts,o,h,l,c,vol FROM stock_kline WHERE company_id=? AND freq='60m' ORDER BY ts", (company_id,))
    ih = senti_all("SELECT ts_hour, post_count_hour, sentiment_direction FROM senti_indicator_hourly WHERE company_id=? ORDER BY ts_hour", (company_id,))
    fig_daily = _quant_fig(kd, idd, "d")
    fig_hourly = _quant_fig(kh, ih, "60m")
    has_price = bool(kd or kh)
    n_posts = senti_one("SELECT COUNT(*) n FROM senti_post WHERE company_id=?", (company_id,))
    n_labeled = senti_one("SELECT COUNT(*) n FROM senti_post WHERE company_id=? AND labeled_by IS NOT NULL", (company_id,))
    # 基本面(现成数据,真展示):营收/净利时序 + 份额 + 估值
    rev = _json_or([], profile.get("revenue_series")) if profile else []
    ni = _json_or([], profile.get("net_income_series")) if profile else []
    shares = query_all("SELECT sub_market, geo, share, share_as_of, rank FROM company_sub_market_share WHERE company_id=? ORDER BY share DESC LIMIT 6", (company_id,)) \
        if _table_exists("company_sub_market_share") else []
    return render_template("monitor.html", co=co, profile=profile, senti=senti, ind=ind, ind_h=ind_h,
                           events=events, spark_pts=sp,
                           fig_daily=json.dumps(fig_daily), fig_hourly=json.dumps(fig_hourly), has_price=has_price,
                           n_posts=(n_posts or {}).get("n", 0), n_labeled=(n_labeled or {}).get("n", 0),
                           rev=rev, ni=ni, shares=shares)


# ════════════════ 三层情绪监控(散户/新闻/热度,三套独立图,绝不混)════════════════
def _senti3_mod():
    import sys as _sys
    from pathlib import Path as _P
    p = str(_P(__file__).resolve().parent.parent / "sentiment")
    if p not in _sys.path:
        _sys.path.insert(0, p)
    import senti3
    return senti3


def _kline_ts(s):
    from datetime import datetime, timezone, timedelta
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone(timedelta(hours=8)))
        except Exception:
            pass
    return None


def _price_3h(company_id):
    """60m K线聚合到 3h 桶网格(OHLC:开=首/高=max/低=min/收=末)。返回 {bucket_id:{o,h,l,c}}。仅交易时段桶有值。"""
    s3 = _senti3_mod()
    rows = senti_all("SELECT ts,o,h,l,c FROM stock_kline WHERE company_id=? AND freq='60m' ORDER BY ts", (company_id,))
    out = {}
    for r in rows:
        dt = _kline_ts(r["ts"])
        if not dt:
            continue
        bid = s3.bucket_for(dt)["bucket_id"]
        if bid not in out:
            out[bid] = {"o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"]}
        else:
            d = out[bid]
            d["h"] = max(d["h"], r["h"]); d["l"] = min(d["l"], r["l"]); d["c"] = r["c"]
    return out


def _window_id_for_price_ts(dt) -> Optional[str]:
    """把交易时段分钟线映射到 V2 盘中窗口；盘前窗口没有成交 K 线。"""
    if not dt or dt.weekday() >= 5:
        return None
    minutes = dt.hour * 60 + dt.minute
    # Yahoo 的 A 股 60m bar 以 09:30/10:30/11:30/12:30/13:30/14:30
    # 标记；12:30 bar 承载午后开盘段，不能误归早盘。
    if 9 * 60 + 30 <= minutes < 12 * 60 + 30:
        slot = "morning"
    elif 12 * 60 + 30 <= minutes < 16 * 60:
        slot = "afternoon"
    else:
        return None
    return f"{dt.date().isoformat()}:{slot}"


def _price_windows(company_id: int) -> dict:
    """60m OHLC 聚合为 morning/afternoon 两个交易窗口。"""
    rows = senti_all(
        "SELECT ts,o,h,l,c FROM stock_kline WHERE company_id=? AND freq='60m' ORDER BY ts",
        (company_id,),
    )
    out = {}
    for row in rows:
        wid = _window_id_for_price_ts(_kline_ts(row.get("ts")))
        if not wid:
            continue
        if wid not in out:
            out[wid] = {"o": row.get("o"), "h": row.get("h"),
                        "l": row.get("l"), "c": row.get("c")}
        else:
            current = out[wid]
            highs = [v for v in (current.get("h"), row.get("h")) if v is not None]
            lows = [v for v in (current.get("l"), row.get("l")) if v is not None]
            current["h"] = max(highs) if highs else None
            current["l"] = min(lows) if lows else None
            current["c"] = row.get("c") if row.get("c") is not None else current.get("c")
    return out


def _bucket_label(bid, scheduled_for=None):
    """返回窗口横轴标签；V2 使用真实执行时点而不是抓取区间截止时点。"""
    # V2:2026-07-15:preopen / legacy:2026-06-15T08:00
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}:(preopen|morning|afternoon)", bid or ""):
        d, slot = bid.rsplit(":", 1)
        slot_name = {"preopen": "盘前", "morning": "早盘", "afternoon": "午后"}[slot]
        scheduled = str(scheduled_for or "").strip()
        # scheduled_for 是 V2 的 canonical 坐标；异常/旧行才按合同默认时点降级。
        if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", scheduled):
            return f"{scheduled[5:10]} {slot_name} {scheduled[11:16]}"
        slot_time = {"preopen": "10:00", "morning": "14:00", "afternoon": "17:00"}
        return f"{d[5:]} {slot_name} {slot_time[slot]}"
    return (bid[5:10] + " " + bid[11:16]) if len(bid) >= 16 else bid


def _nontrading(bid):
    if (bid or "").endswith(":preopen"):
        return True
    try:
        return int(bid[11:13]) in (17, 20)        # 17-20 / 20-次日08 桶:非交易 → 灰底
    except Exception:
        return False


def _rolling_mean(values: list, width: int = 5, min_periods: int = 2) -> list:
    out = []
    for i in range(len(values)):
        # 当前横轴没有原始观察时均线也必须缺失，不能把历史均值外推成“当前值”。
        if values[i] is None:
            out.append(None)
            continue
        window = [float(v) for v in values[max(0, i - width + 1):i + 1]
                  if v is not None and math.isfinite(float(v))]
        out.append(sum(window) / len(window) if len(window) >= min_periods else None)
    return out


def _timeline_sort_key(key: str, scheduled_for: str | None = None) -> tuple[str, str]:
    """把 legacy bucket 与 V2 window 映射到同一可排序时间轴。"""
    raw = str(scheduled_for or "").strip()
    if raw:
        return raw[:16].replace("T", " "), key
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}):(preopen|morning|afternoon)", key or "")
    if match:
        slot_time = {"preopen": "10:00", "morning": "14:00", "afternoon": "17:00"}
        return f"{match.group(1)} {slot_time[match.group(2)]}", key
    return str(key or "")[:16].replace("T", " "), key


def _weekday_value(value: str | None) -> bool:
    """仅对可识别日期排除周末；异常 legacy key 留给上层显示为数据问题。"""
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").weekday() < 5
    except (TypeError, ValueError):
        return True


def _company_retail_summary_rows(company_id: int) -> list[dict]:
    """返回连续的 legacy + V2 散户序列，字段统一供 KPI 与监控摘要使用。"""
    legacy = senti_all(
        "SELECT * FROM senti_retail_bucket WHERE company_id=? ORDER BY bucket_start",
        (company_id,),
    ) if _senti_table_exists("senti_retail_bucket") else []
    legacy = [row for row in legacy if _weekday_value(row.get("bucket_start"))]
    v2 = senti_all(
        """SELECT w.*,l.session_date,l.scheduled_for,l.status AS window_status,
                  l.source_status_json
           FROM senti_retail_window w JOIN retail_window_ledger l ON l.window_id=w.window_id
           WHERE w.company_id=? ORDER BY l.scheduled_for,w.window_id""",
        (company_id,),
    ) if (_senti_table_exists("senti_retail_window")
          and _senti_table_exists("retail_window_ledger")) else []
    if v2:
        cutoff = min(str(row.get("session_date") or row.get("window_id") or "")[:10]
                     for row in v2)
        legacy = [row for row in legacy if str(row.get("bucket_start") or "")[:10] < cutoff]
    out = []
    for row in legacy:
        out.append({
            "key": row.get("bucket_id"), "timeline": row.get("bucket_start"),
            "scored_count": row.get("valid_count") or 0,
            "raw_count": (row.get("layer_total") if row.get("layer_total") is not None
                          else row.get("valid_count") or 0),
            "net_weighted": row.get("net_sentiment_weighted"),
            "net_plain": (row.get("net_sentiment_plain") if row.get("net_sentiment_plain") is not None
                          else row.get("net_sentiment")),
            "coverage": row.get("coverage"), "usable": row.get("usable") or 0,
            "display_ready": bool(row.get("usable")),
            # legacy 聚合没有来源级审计；只要已形成有效评分，就按“评分已产出”
            # 展示，usable 仍只代表样本显著，避免把低样本误写成未完成。
            "score_complete": bool((row.get("valid_count") or 0) > 0),
            "significant": bool(row.get("usable")),
            "n_xueqiu": row.get("n_xueqiu") or 0, "n_eastmoney": row.get("n_eastmoney") or 0,
            "n_guba": row.get("n_guba") or 0, "n_ths": row.get("n_ths") or 0,
            "mode": "legacy",
        })
    for row in v2:
        statuses = _json_or({}, row.get("source_status_json"))
        score_complete = (
            statuses.get("score") == "complete"
            if statuses else row.get("window_status") == "complete"
        )
        significant = row.get("significant")
        if significant is None:
            significant = row.get("usable")
        out.append({
            "key": row.get("window_id"), "timeline": row.get("scheduled_for"),
            "scored_count": row.get("scored_count") or 0, "raw_count": row.get("raw_count") or 0,
            "net_weighted": row.get("net_weighted"), "net_plain": row.get("net_plain"),
            "coverage": row.get("coverage"), "usable": row.get("usable") or 0,
            "display_ready": bool(score_complete and significant),
            "score_complete": bool(score_complete), "significant": bool(significant),
            "n_xueqiu": row.get("n_xueqiu") or 0, "n_eastmoney": row.get("n_eastmoney") or 0,
            "n_guba": row.get("n_guba") or 0, "n_ths": row.get("n_ths") or 0,
            "mode": "v2",
        })
    return sorted(out, key=lambda row: _timeline_sort_key(row.get("key"), row.get("timeline")))


def _latest_retail_summary_row(rows: list[dict]) -> dict | None:
    """选择 KPI 展示行，并与主图的“已完成情绪”口径保持一致。

    优先取最新 display-ready 行；若尚无完整评分，再回退到最新已有评分行，
    使页面能透明展示阶段结果，并由调用方精确区分低样本与评分进行中。
    同一交易日内，具体 10/14/17 点窗口优先于 23:59 的日线汇总，避免
    “三窗尚未齐”的汇总行覆盖已经真实产出的窗口分数。
    """
    def preference(row: dict) -> tuple[str, int, tuple[str, str]]:
        timeline = _timeline_sort_key(str(row.get("key") or ""), row.get("timeline"))
        mode = str(row.get("mode") or "")
        is_daily = "daily" in mode or bool(
            re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("key") or ""))
        )
        return timeline[0][:10], 0 if is_daily else 1, timeline

    scored = [
        row for row in rows
        if (row.get("scored_count") or 0) > 0
        and (row.get("net_weighted") is not None or row.get("net_plain") is not None)
    ]
    ready = [row for row in scored if row.get("display_ready")]
    return max(ready or scored, key=preference) if (ready or scored) else None


_AX3 = dict(gridcolor="rgba(255,255,255,.08)", zerolinecolor="rgba(255,255,255,.20)",
            linecolor="rgba(255,255,255,.22)", color="#c9d6ea", tickfont={"size": 10, "color": "#aebbd4"})


def _gray_bands(cats):
    """非交易桶灰底阴影(categorical x,索引定位)。"""
    sh = []
    for i, b in enumerate(cats):
        if _nontrading(b):
            sh.append({"type": "rect", "xref": "x", "yref": "paper", "x0": i - 0.5, "x1": i + 0.5,
                       "y0": 0, "y1": 1, "fillcolor": "rgba(120,135,170,.10)", "line": {"width": 0}, "layer": "below"})
    return sh


def _layer_fig(cats, price3h, srows, kind):
    """散户/新闻情绪图:股价 3h K线(主轴)+ 该层净情绪线(副轴 [-1,1])。共享 categorical 3h 轴。
    kind='retail' 用加权净情绪(主线)+ 原始(hover);'news' 用净情绪。非交易桶灰底。"""
    if not cats:
        return None
    labels = [_bucket_label(b) for b in cats]
    smap = {r["bucket_id"]: r for r in srows}
    op = [price3h.get(b, {}).get("o") for b in cats]
    hp = [price3h.get(b, {}).get("h") for b in cats]
    lp = [price3h.get(b, {}).get("l") for b in cats]
    cp = [price3h.get(b, {}).get("c") for b in cats]
    has_price = any(v is not None for v in cp)
    def _plain(b):
        r = smap.get(b, {})
        return r.get("net_sentiment_plain") if r.get("net_sentiment_plain") is not None else r.get("net_sentiment")

    def _weighted(b):
        r = smap.get(b, {})
        return r.get("net_sentiment_weighted") if r.get("net_sentiment_weighted") is not None else _plain(b)
    usable = [smap.get(b, {}).get("usable") for b in cats]
    cov = [smap.get(b, {}).get("coverage") for b in cats]
    #  抽样口径:加权为主线(热度+来源权重),不加权 plain 入 hover;只画 usable=1 桶(6/1 前低覆盖/未打分桶不画,绝不用低覆盖分冒充)
    sline = [(_weighted(b) if smap.get(b, {}).get("usable") else None) for b in cats]
    sraw = [_plain(b) for b in cats]
    vcnt = [smap.get(b, {}).get("valid_count") for b in cats]
    color = "#7cc4ff" if kind == "retail" else "#ffc24b"
    sname = "散户净情绪(加权)" if kind == "retail" else "新闻净情绪(加权)"
    msize = [7 if (u and v and v > 10) else 4 for u, v in zip(usable, vcnt)]
    covpct = [(("%.0f%%" % (c * 100)) + ("·抽样估计" if c < 0.5 else "")) if c is not None else "—" for c in cov]
    data = []
    if has_price:
        data.append({"type": "candlestick", "x": labels, "open": op, "high": hp, "low": lp, "close": cp,
                     "name": "股价(3h)", "yaxis": "y",
                     "increasing": {"line": {"color": "#ff5b52"}, "fillcolor": "#ff5b52"},
                     "decreasing": {"line": {"color": "#22c08a"}, "fillcolor": "#22c08a"}})
    data.append({"type": "scatter", "mode": "lines+markers", "x": labels, "y": sline, "name": sname,
                 "yaxis": "y2", "line": {"color": color, "width": 2}, "connectgaps": False,
                 "marker": {"size": msize, "color": color},
                 "customdata": [[r if r is not None else "—", v if v is not None else 0, cp] for r, v, cp in zip(sraw, vcnt, covpct)],
                 "hovertemplate": "%{x}<br>" + sname + ": %{y:.2f}<br>不加权净: %{customdata[0]}<br>有效条数: %{customdata[1]}<br>覆盖率: %{customdata[2]}<extra></extra>"})
    dom_price = [0.42, 1.0] if has_price else [0.55, 1.0]
    layout = {
        "height": 360, "margin": {"l": 48, "r": 14, "t": 8, "b": 64},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(255,255,255,.02)",
        "showlegend": True, "legend": {"orientation": "h", "y": 1.08, "x": 0, "font": {"color": "#dde7f6", "size": 11}},
        "hoverlabel": {"bgcolor": "#0e1830", "bordercolor": "#5a78b0", "font": {"color": "#eaf2ff", "size": 12}},
        "shapes": _gray_bands(cats),
        "xaxis": {**_AX3, "type": "category", "anchor": "y2", "tickangle": -45, "nticks": 14,
                  "rangeslider": {"visible": False}},
        "yaxis": {**_AX3, "domain": dom_price, "title": {"text": "股价", "font": {"size": 11, "color": "#c9d6ea"}}, "autorange": True},
        "yaxis2": {**_AX3, "domain": [0.0, dom_price[0] - 0.06],
                   "title": {"text": "净情绪[-1,1]", "font": {"size": 11, "color": "#c9d6ea"}},
                   "range": [-1.05, 1.05], "dtick": 0.5, "zeroline": True, "fixedrange": True},
        "hovermode": "x unified", "dragmode": "zoom",
    }
    return {"data": data, "layout": layout, "has_price": has_price}


def _heat_fig(cats, hrows):
    """热度图:发帖量 3h 柱(per_hour 归一,防隔夜桶虚高)。独立,绝不并入情绪。autoscale。"""
    if not cats:
        return None
    labels = [_bucket_label(b) for b in cats]
    hmap = {r["bucket_id"]: r for r in hrows}
    ph = [round(hmap.get(b, {}).get("per_hour_count") or 0, 2) for b in cats]
    tot = [hmap.get(b, {}).get("total_count") or 0 for b in cats]
    rc = [hmap.get(b, {}).get("retail_count") or 0 for b in cats]
    nc = [hmap.get(b, {}).get("news_count") or 0 for b in cats]
    data = [{"type": "bar", "x": labels, "y": ph, "name": "发帖量/小时",
             "marker": {"color": "rgba(110,170,255,.72)"},
             "customdata": [[t, r, n] for t, r, n in zip(tot, rc, nc)],
             "hovertemplate": "%{x}<br>每小时: %{y}<br>桶内总条: %{customdata[0]}<br>散户: %{customdata[1]} 新闻: %{customdata[2]}<extra></extra>"}]
    layout = {
        "height": 240, "margin": {"l": 48, "r": 14, "t": 8, "b": 64},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(255,255,255,.02)",
        "showlegend": False, "shapes": _gray_bands(cats),
        "hoverlabel": {"bgcolor": "#0e1830", "bordercolor": "#5a78b0", "font": {"color": "#eaf2ff", "size": 12}},
        "xaxis": {**_AX3, "type": "category", "tickangle": -45, "nticks": 14},
        "yaxis": {**_AX3, "title": {"text": "发帖量/小时", "font": {"size": 11, "color": "#c9d6ea"}}, "autorange": True},
        "dragmode": "zoom",
    }
    return {"data": data, "layout": layout}


def _category_ticks(labels: list[str], limit: int = 10) -> list[str]:
    """类别轴等距抽样且始终保留首末坐标，避免最新窗口被 Plotly 自动省略。"""
    if len(labels) <= limit:
        return labels
    indices = {
        round(index * (len(labels) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [labels[index] for index in sorted(indices)]


def _panel_fig(cats, price_map, senti_map, vol_map, kind="retail", freq="window",
               draft_map=None, timeline_map=None):
    """股价、散户情绪和散户发帖量三栏同轴图，MA5 通过图例可隐藏/显示。"""
    if not cats:
        return None
    timeline_map = timeline_map or {}
    labels = [(_bucket_label(c, timeline_map.get(c)) if freq in ("3h", "window") else c[5:])
              for c in cats]
    op = [price_map.get(c, {}).get("o") for c in cats]
    hp = [price_map.get(c, {}).get("h") for c in cats]
    lp = [price_map.get(c, {}).get("l") for c in cats]
    cp = [price_map.get(c, {}).get("c") for c in cats]
    has_price = any(v is not None for v in cp)
    draft_map = draft_map or {}

    def _sentiment_draft(c):
        state = draft_map.get(c, {})
        return bool(state.get("sentiment_draft", c in draft_map))

    def _volume_draft(c):
        state = draft_map.get(c, {})
        if "volume_draft" in state:
            return bool(state["volume_draft"])
        return "未完成" in str(state.get("status", ""))

    # 已经算出的真实分数和真实发帖量始终留在各自主轨迹中；低样本或进行中
    # 仅改变点/柱样式及悬浮说明。拆成额外“草稿”轨迹会让日线从约定的
    # 五条轨迹膨胀到七条，也会造成“明明有分数却像没有数据”的误解。
    sline = [senti_map.get(c) for c in cats]
    # 没有聚合行代表“数据不可得”，不能伪装为 0 发帖；真实 0 由 map 中的 0 保留。
    raw_vol = [round(vol_map[c], 1) if c in vol_map and vol_map[c] is not None else None
               for c in cats]
    vol = raw_vol
    gray = [i for i, c in enumerate(cats) if freq in ("3h", "window") and _nontrading(c)]
    color = "#7cc4ff"
    sname = "散户净情绪"
    senti_ma = _rolling_mean(sline, 5)
    vol_ma = _rolling_mean(vol, 5)
    data = []
    if has_price:
        data.append({"type": "candlestick", "x": labels, "open": op, "high": hp, "low": lp, "close": cp,
                      "name": "股价", "yaxis": "y",
                      "increasing": {"line": {"color": "#ff5b52"}, "fillcolor": "#ff5b52"},
                      "decreasing": {"line": {"color": "#22c08a"}, "fillcolor": "#22c08a"}})
    source_notes = [
        draft_map.get(c, {}).get("source_note")
        or draft_map.get(c, {}).get("status")
        or "来源完整"
        for c in cats
    ]
    sentiment_marker_colors = ["#fbbf24" if _sentiment_draft(c) else color for c in cats]
    sentiment_marker_symbols = ["circle-open" if _sentiment_draft(c) else "circle" for c in cats]
    sentiment_marker_sizes = [7 if _sentiment_draft(c) else 5 for c in cats]
    data.append({"type": "scatter", "mode": "lines+markers", "x": labels, "y": sline, "name": sname,
                 "yaxis": "y2", "line": {"color": color, "width": 2}, "connectgaps": False,
                 "marker": {"size": sentiment_marker_sizes, "color": sentiment_marker_colors,
                            "symbol": sentiment_marker_symbols},
                 "customdata": source_notes,
                 "hovertemplate": "%{x}<br>散户净情绪 %{y:.3f}<br>%{customdata}<extra></extra>"})
    data.append({"type": "scatter", "mode": "lines", "x": labels, "y": senti_ma,
                 "name": "散户情绪 MA5", "yaxis": "y2", "visible": "legendonly",
                 "line": {"color": "#d8b4fe", "width": 2, "dash": "dot"}, "connectgaps": False,
                 "hovertemplate": "%{x}<br>散户情绪 MA5 %{y:.3f}<extra></extra>"})
    volume_colors = [
        "rgba(251,191,36,.45)" if _volume_draft(c) else "rgba(150,160,185,.6)"
        for c in cats
    ]
    data.append({"type": "bar", "x": labels, "y": vol, "name": "发帖量", "yaxis": "y3",
                 "marker": {"color": volume_colors},
                 "customdata": source_notes,
                 "hovertemplate": "%{x}<br>发帖量 %{y:.1f}<br>%{customdata}<extra></extra>"})   # 热度=中性灰,与情绪线(蓝/金)区分色
    data.append({"type": "scatter", "mode": "lines", "x": labels, "y": vol_ma,
                 "name": "发帖量 MA5", "yaxis": "y3", "visible": "legendonly",
                 "line": {"color": "#f9a8d4", "width": 2, "dash": "dot"}, "connectgaps": False,
                 "hovertemplate": "%{x}<br>发帖量 MA5 %{y:.1f}<extra></extra>"})
    shapes = [{"type": "rect", "xref": "x", "yref": "paper", "x0": i - 0.5, "x1": i + 0.5,
               "y0": 0, "y1": 1, "fillcolor": "rgba(120,135,170,.10)", "line": {"width": 0}, "layer": "below"} for i in gray]
    layout = {
        "height": 520, "margin": {"l": 50, "r": 14, "t": 8, "b": 60},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(255,255,255,.02)",
        "showlegend": True, "legend": {"orientation": "h", "y": 1.05, "x": 0, "font": {"color": "#dde7f6", "size": 11}},
        "hoverlabel": {"bgcolor": "#0e1830", "bordercolor": "#5a78b0", "font": {"color": "#eaf2ff", "size": 12}},
        "shapes": shapes, "hovermode": "x unified",
        "xaxis": {**_AX3, "type": "category", "anchor": "y3", "tickangle": -45,
                  "tickmode": "array", "tickvals": _category_ticks(labels),
                  "ticktext": _category_ticks(labels), "rangeslider": {"visible": False}},
        "yaxis": {**_AX3, "domain": [0.46, 1.0], "visible": has_price,
                  "title": {"text": "股价", "font": {"size": 11, "color": "#c9d6ea"}},
                  "autorange": True},
        "yaxis2": {**_AX3, "domain": ([0.24, 0.43] if has_price else [0.45, 1.0]), "title": {"text": sname + "[-1,1]", "font": {"size": 10, "color": "#c9d6ea"}},
                    "range": [-1.05, 1.05], "dtick": 0.5, "zeroline": True, "fixedrange": True},
        "yaxis3": {**_AX3, "domain": ([0.0, 0.21] if has_price else [0.0, 0.39]),
                   "title": {"text": "发帖量", "font": {"size": 10, "color": "#c9d6ea"}},
                   "autorange": True, "rangemode": "tozero"},
    }
    return {"data": data, "layout": layout, "has_price": has_price}


def _company_panels(company_id):
    """构建连续的 legacy→V2 窗口/交易日综合图。"""
    NW, ND = 66, 50

    def _wp(row, weighted="net_sentiment_weighted", plain="net_sentiment_plain", legacy="net_sentiment"):
        return row.get(weighted) if row.get(weighted) is not None \
            else (row.get(plain) if row.get(plain) is not None else row.get(legacy))

    legacy_windows = senti_all(
        "SELECT * FROM senti_retail_bucket WHERE company_id=? ORDER BY bucket_start", (company_id,)
    ) if _senti_table_exists("senti_retail_bucket") else []
    legacy_windows = [row for row in legacy_windows if _weekday_value(row.get("bucket_start"))]
    legacy_heat = senti_all(
        "SELECT * FROM heat_volume_bucket WHERE company_id=? ORDER BY bucket_start", (company_id,)
    ) if _senti_table_exists("heat_volume_bucket") else []
    legacy_heat = [row for row in legacy_heat if _weekday_value(row.get("bucket_start"))]
    v2_windows = senti_all(
        """SELECT w.*, l.session_date, l.slot, l.scheduled_for,
                  l.status AS window_status, l.source_status_json
           FROM senti_retail_window w JOIN retail_window_ledger l ON l.window_id=w.window_id
           WHERE w.company_id=? ORDER BY l.scheduled_for, w.window_id""", (company_id,)
    ) if (_senti_table_exists("senti_retail_window")
          and _senti_table_exists("retail_window_ledger")) else []
    # 价格只能落到已经实际启动过的调度窗口。否则 10:00 的实时 10:30 bar 会在
    # 14:00 任务尚未执行时提前制造一个“早盘 14:00”未来坐标。
    active_ledgers = senti_all(
        """SELECT window_id,scheduled_for,status
           FROM retail_window_ledger
           WHERE status<>'pending' ORDER BY scheduled_for,window_id"""
    ) if _senti_table_exists("retail_window_ledger") else []

    cutoff = None
    if v2_windows:
        cutoff = min(str(row.get("session_date") or row.get("window_id") or "")[:10]
                     for row in v2_windows)
        legacy_windows = [row for row in legacy_windows
                          if str(row.get("bucket_start") or "")[:10] < cutoff]
        legacy_heat = [row for row in legacy_heat
                       if str(row.get("bucket_start") or "")[:10] < cutoff]
    p_legacy = _price_3h(company_id)
    p_v2 = _price_windows(company_id)
    if cutoff:
        p_legacy = {key: value for key, value in p_legacy.items() if key[:10] < cutoff}
        active_window_ids = {row["window_id"] for row in active_ledgers}
        p_v2 = {key: value for key, value in p_v2.items()
                if key[:10] >= cutoff and key in active_window_ids}
    else:
        p_v2 = {}
    pW = {**p_legacy, **p_v2}
    sW = {row["bucket_id"]: _wp(row) for row in legacy_windows
          if (row.get("valid_count") or 0) > 0}
    sW.update({row["window_id"]: (row.get("net_weighted")
                                  if row.get("net_weighted") is not None else row.get("net_plain"))
               for row in v2_windows if (row.get("scored_count") or 0) > 0})
    vW = {row["bucket_id"]: row.get("retail_count") or 0 for row in legacy_heat}
    vW.update({row["window_id"]: row.get("raw_count") or 0 for row in v2_windows})
    scheduled = {row["window_id"]: row.get("scheduled_for") for row in active_ledgers}
    scheduled.update({row["window_id"]: row.get("scheduled_for") for row in v2_windows})
    draftW = {}
    for row in v2_windows:
        statuses = _json_or({}, row.get("source_status_json"))
        fallback_complete = row.get("window_status") == "complete"
        score_complete = statuses.get("score") == "complete" if statuses else fallback_complete
        volume_complete = statuses.get("guba") in {"complete", "empty"} if statuses else fallback_complete
        significant = row.get("significant")
        if significant is None:
            # 兼容迁移前/测试夹具；V2 live 应始终有 significant。
            significant = row.get("usable")
        sentiment_draft = not score_complete or not significant
        volume_draft = not volume_complete
        enrichment_partial = bool(statuses) and statuses.get("xinghan") not in {"complete", "empty"}
        if not sentiment_draft and not volume_draft and not enrichment_partial:
            continue
        if not score_complete:
            status = "评分进行中"
        elif not significant:
            status = "低样本"
        else:
            status = "抓取未完成"
        draftW[row["window_id"]] = {
            "status": status,
            "coverage": row.get("coverage"),
            "sentiment_draft": sentiment_draft,
            "volume_draft": volume_draft,
            "source_note": (
                "舆情附加源补抓中；股吧与评分已完成"
                if enrichment_partial and score_complete and volume_complete
                else status
            ),
        }
    window_keys = set(sW) | set(vW) | set(pW)
    catsW = sorted(window_keys,
                   key=lambda key: _timeline_sort_key(key, scheduled.get(key)))[-NW:]

    legacy_daily = senti_all(
        "SELECT * FROM senti_retail_daily WHERE company_id=? ORDER BY trade_date", (company_id,)
    ) if _senti_table_exists("senti_retail_daily") else []
    legacy_hd = senti_all(
        "SELECT * FROM heat_volume_daily WHERE company_id=? ORDER BY trade_date", (company_id,)
    ) if _senti_table_exists("heat_volume_daily") else []
    v2_daily = senti_all(
        "SELECT * FROM senti_retail_trading_daily WHERE company_id=? ORDER BY session_date",
        (company_id,),
    ) if _senti_table_exists("senti_retail_trading_daily") else []
    if v2_daily:
        daily_cutoff = min(str(row.get("session_date") or "")[:10] for row in v2_daily)
        legacy_daily = [row for row in legacy_daily if str(row.get("trade_date") or "") < daily_cutoff]
        legacy_hd = [row for row in legacy_hd if str(row.get("trade_date") or "") < daily_cutoff]
    sD = {row["trade_date"]: _wp(row) for row in legacy_daily
          if (row.get("valid_count") or 0) > 0}
    sD.update({row["session_date"]: (row.get("net_weighted")
                                     if row.get("net_weighted") is not None else row.get("net_plain"))
               for row in v2_daily if (row.get("scored_count") or 0) > 0})
    vD = {row["trade_date"]: row.get("retail_count") or 0 for row in legacy_hd}
    vD.update({row["session_date"]: row.get("raw_count") or 0 for row in v2_daily})
    draftD = {
        row["session_date"]: {
            "status": ("当日汇总中" if not row.get("complete") else "低样本"),
            "coverage": row.get("coverage"),
            "sentiment_draft": not row.get("complete") or not row.get("usable"),
            "volume_draft": not row.get("complete"),
        }
        for row in v2_daily if not row.get("complete") or not row.get("usable")
    }

    pdrows = senti_all("SELECT ts,o,h,l,c FROM stock_kline WHERE company_id=? AND freq='d' ORDER BY ts", (company_id,))
    pD = {r["ts"]: {"o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"]} for r in pdrows}
    daily_keys = set(sD) | set(vD) | set(pD)
    catsD = sorted(d for d in daily_keys
                   if datetime.strptime(d[:10], "%Y-%m-%d").weekday() < 5)[-ND:]
    return {
        "retail_window": _panel_fig(catsW, pW, sW, vW, "retail", "window", draftW,
                                    timeline_map=scheduled),
        "retail_d": _panel_fig(catsD, pD, sD, vD, "retail", "d", draftD),
        "has_daily_price": bool(pD), "has_window_price": bool(pW),
        "data_mode": ("hybrid" if v2_windows and legacy_windows else
                      ("v2" if v2_windows else "legacy")),
    }


@app.route("/dynamic/monitor3/<int:company_id>")
def monitor3(company_id):
    """单公司散户情绪监控：股价、散户净情绪、散户发帖量共用窗口轴。"""
    canonical_id = company_id
    if _senti_table_exists("company_id_redirect"):
        redirected = senti_one(
            "SELECT canonical_company_id FROM company_id_redirect WHERE old_company_id=?",
            (company_id,),
        )
        if redirected:
            canonical_id = int(redirected["canonical_company_id"])
    is_new_stock = False
    co = query_one("SELECT * FROM company WHERE id=?", (canonical_id,))
    if not co:
        sc = senti_one("SELECT id, name, ticker FROM senti_company WHERE id=?", (canonical_id,))
        if not sc:
            abort(404)
        co = {"id": sc["id"], "name": sc["name"], "ticker": sc["ticker"] or "新股·待补代码"}
        is_new_stock = True
    panels = _company_panels(canonical_id)
    retail = _company_retail_summary_rows(canonical_id)
    latest_rows = retail[-66:]
    retail_src = {
        "雪球": sum(r.get("n_xueqiu") or 0 for r in latest_rows),
        "东财股吧": sum((r.get("n_eastmoney") or 0) + (r.get("n_guba") or 0) for r in latest_rows),
        "同花顺": sum(r.get("n_ths") or 0 for r in latest_rows),
    }
    valid_key, raw_key = "scored_count", "raw_count"
    weighted_key, plain_key = "net_weighted", "net_plain"
    weights = (_senti3_mod().load_layer_config().get("retail", {}) or {}).get(
        "weights", {"xueqiu": 1.0, "eastmoney": 1.0, "ths": 1.0, "guba": 1.0})
    latest = _latest_retail_summary_row(latest_rows)
    latest_net = None
    if latest:
        latest_net = latest.get(weighted_key) if latest.get(weighted_key) is not None else latest.get(plain_key)
    summ = {
        "retail_valid": sum(r.get(valid_key) or 0 for r in latest_rows),
        "retail_latest": latest_net,
        "retail_plain": latest.get(plain_key) if latest else None,
        "retail_cov": latest.get("coverage") if latest else None,
        "retail_usable": bool(latest and latest.get("usable")),
        "retail_display_ready": bool(latest and latest.get("display_ready")),
        "retail_quality_label": (
            None
            if not latest or latest.get("display_ready")
            else ("低样本" if latest.get("score_complete") else "评分进行中")
        ),
        "heat_total": sum(r.get(raw_key) or 0 for r in latest_rows),
        "has_price": panels.get("has_window_price") or panels.get("has_daily_price"),
    }
    return render_template("monitor3.html", co=co, weights=weights, is_new_stock=is_new_stock,
                           retail_src=retail_src, summ=summ, panels_json=json.dumps(panels))


@app.route("/dynamic/proxy/job")
def proxy_job():
    """招聘代理变量页(金融视角,按公司):每家在招什么职能 · 在哪招 · 招多少 · 本周新增。"""
    import datetime as _dt
    from collections import Counter, defaultdict
    sources = senti_all("""SELECT s.company_id, s.ticker, s.name, s.career_url, s.extractor, s.status,
               s.last_checked, s.n_jobs, s.scrape_path, s.platform_type
               FROM recruit_source s ORDER BY (s.status='ok') DESC, s.n_jobs DESC, s.name""")
    jobs = senti_all("""SELECT ticker, title, dept, location, location_city, job_function, domain,
               first_seen, last_seen FROM recruit_job WHERE status='open'
               ORDER BY first_seen DESC, title""")
    recent = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
    # 公司主营行业(research.db 只读;按 主营 role + 营收占比取首位)
    ind_map = {}
    for row in query_all("""SELECT ci.company_id cid, i.name iname
            FROM company_industry ci JOIN industry i ON i.id=ci.industry_id
            ORDER BY ci.company_id, (ci.role='主营') DESC, ci.revenue_share DESC"""):
        ind_map.setdefault(row["cid"], row["iname"])
    by_tk = defaultdict(list)
    for j in jobs:
        j["is_new"] = (j["first_seen"] or "")[:10] >= recent
        by_tk[j["ticker"]].append(j)
    # ── 按公司聚合:每家 → 职能分布(每职能:数量 + 城市拆解)+ 本周新增岗位 ──
    companies = []
    for s in sources:
        if s["status"] != "ok" or not by_tk.get(s["ticker"]):
            continue
        jl = by_tk[s["ticker"]]
        func_map = defaultdict(lambda: {"n": 0, "cities": Counter(), "new": 0})
        for j in jl:
            f = j["job_function"] or "其它"
            func_map[f]["n"] += 1
            if j["location_city"]:
                func_map[f]["cities"][j["location_city"]] += 1
            if j["is_new"]:
                func_map[f]["new"] += 1
        funcs = []
        for f, d in sorted(func_map.items(), key=lambda x: -x[1]["n"]):
            funcs.append({"func": f, "n": d["n"], "new": d["new"],
                          "cities": d["cities"].most_common(4)})
        new_jobs = [{"title": j["title"], "func": j["job_function"], "domain": j["domain"],
                     "location": j["location"] or j["location_city"] or ""}
                    for j in jl if j["is_new"]][:30]
        domains = Counter()
        for j in jl:
            for dm in (j["domain"] or "").split(","):
                if dm.strip():
                    domains[dm.strip()] += 1
        companies.append({
            "company_id": s["company_id"], "name": s["name"], "ticker": s["ticker"],
            "ind": ind_map.get(s["company_id"]) or "未分类",
            "n_open": len(jl), "n_new": sum(1 for j in jl if j["is_new"]),
            "funcs": funcs, "new_jobs": new_jobs, "domains": domains.most_common(4),
            "career_url": s["career_url"],
        })
    namemap = {c["ticker"]: c["name"] for c in sources}
    chg = senti_all("""SELECT ticker, run_date, n_open, n_new, n_closed, new_titles, closed_titles
                       FROM recruit_change_log WHERE n_new>0 OR n_closed>0
                       ORDER BY run_date DESC, id DESC LIMIT 40""")
    for c in chg:
        c["name"] = namemap.get(c["ticker"], c["ticker"])
        c["new_list"] = _json_or([], c.get("new_titles"))
        c["closed_list"] = _json_or([], c.get("closed_titles"))
    tot_open = sum(s["n_jobs"] or 0 for s in sources if s["status"] == "ok")
    n_ok = sum(1 for s in sources if s["status"] == "ok")
    n_new7 = sum(1 for j in jobs if j["is_new"])
    # 行业筛选下拉:按在招公司数降序,未分类殿后
    _ic = Counter(c["ind"] for c in companies)
    inds = sorted(_ic.keys(), key=lambda x: (x == "未分类", -_ic[x], x))
    return render_template("proxy_job.html", sources=sources, companies=companies, recent=recent,
                           changes=chg, tot_open=tot_open, n_ok=n_ok, n_src=len(sources), n_new7=n_new7,
                           inds=inds, ind_counts=_ic)


@app.route("/dynamic/chain")
def chain_sentiment():
    """产业链上下游图(T6):industry_relation 行业级有向图 + 成分股聚合情绪叠加。缺权重诚实标注。"""
    edges = query_all("""SELECT r.upstream_id u, r.downstream_id d, r.relation_type rt,
        r.cost_share cs, r.demand_share ds, r.bargaining_power bp
        FROM industry_relation r""")
    names = {row["id"]: row["name"] for row in query_all("SELECT id, name FROM industry")}
    # 每行业聚合情绪(覆盖到的成分股最新值;senti.db JOIN research.company_industry 只读)
    sib = {}
    for row in senti_all("""SELECT ci.industry_id iid, AVG(i.sentiment_direction) dir,
               AVG(i.post_count) pc, COUNT(DISTINCT i.company_id) n
        FROM senti_indicator_daily i
        JOIN (SELECT company_id, MAX(trade_date) md FROM senti_indicator_daily GROUP BY company_id) m
          ON m.company_id=i.company_id AND m.md=i.trade_date
        JOIN company_industry ci ON ci.company_id=i.company_id
        GROUP BY ci.industry_id"""):
        sib[row["iid"]] = row
    node_ids = set()
    for e in edges:
        node_ids.add(e["u"]); node_ids.add(e["d"])
    cnodes = []
    for nid in sorted(node_ids):
        s = sib.get(nid)
        d = s["dir"] if s else None
        col = "#e0584a" if (d is not None and d > 0.08) else "#2f8d59" if (d is not None and d < -0.08) else "#9fb0c4"
        cnodes.append({"data": {"id": str(nid), "label": names.get(nid, str(nid)),
                                "dir": (round(d, 2) if d is not None else None),
                                "n": (s["n"] if s else 0), "col": col}})
    cedges = []
    for i, e in enumerate(edges):
        if e["u"] in node_ids and e["d"] in node_ids:
            cedges.append({"data": {"id": "e%d" % i, "source": str(e["u"]), "target": str(e["d"]),
                                    "rt": e["rt"] or "供应", "weighted": 1 if (e["cs"] or e["ds"]) else 0}})
    return render_template("chain_sentiment.html",
                           cnodes=json.dumps(cnodes, ensure_ascii=False), cedges=json.dumps(cedges, ensure_ascii=False),
                           n_edges=len(edges), n_cov=len(sib), n_nodes=len(node_ids))


def _supplychain_senti():
    """funda 节点 ticker → 我们自算情绪方向(仅覆盖到的;交集很小,其余置灰)。"""
    out = {}
    for r in senti_all("""SELECT c.ticker tk, AVG(i.sentiment_direction) dir
        FROM senti_indicator_daily i
        JOIN (SELECT company_id, MAX(trade_date) md FROM senti_indicator_daily GROUP BY company_id) m
          ON m.company_id=i.company_id AND m.md=i.trade_date
        JOIN company c ON c.id=i.company_id
        WHERE c.ticker IS NOT NULL AND i.sentiment_direction IS NOT NULL GROUP BY c.ticker"""):
        out[r["tk"]] = r["dir"]
        out[r["tk"].split(".")[0]] = r["dir"]      # 兼容去后缀匹配
    return out


def _name_map():
    """research.db ticker → 中文名(A股节点用中文名;funda 外资用英文名)。"""
    m = {}
    for r in query_all("SELECT ticker, name FROM company WHERE ticker IS NOT NULL AND TRIM(ticker)<>''"):
        m[r["ticker"]] = r["name"]
        m[r["ticker"].split(".")[0]] = r["name"]
    return m


@app.route("/dynamic/supplychain")
def supplychain():
    """V3/T12:1:1 还原 funda 半导体供应链(关系图 ego + 列表双视图)。节点用公司名,情绪叠加用自算。"""
    nodes = senti_all("SELECT ticker, name, layer, country FROM funda_semi_nodes")
    sdir = _supplychain_senti()
    rmap = _name_map()
    # 下拉/检索用节点清单(ticker — 公司名)
    optlist = []
    for n in nodes:
        disp = rmap.get(n["ticker"]) or rmap.get((n["ticker"] or "").split(".")[0]) or n["name"] or n["ticker"]
        optlist.append({"tk": n["ticker"], "nm": disp})
    optlist.sort(key=lambda x: x["nm"])
    n_layers = len({(n["layer"] or "其它") for n in nodes})
    # 按行业 tag 检索公司:research.db 只读 — company_industry × industry × company
    # 一次性塞进模板,前端下拉切换即时显示(公司量级几百,纯前端可行)
    tagmap = {}
    for r in query_all("""SELECT i.name tag, co.name nm, co.ticker tk
        FROM company_industry ci
        JOIN industry i ON i.id = ci.industry_id
        JOIN company   co ON co.id = ci.company_id
        ORDER BY i.name, co.name"""):
        tagmap.setdefault(r["tag"], []).append({"name": r["nm"], "ticker": r["tk"] or ""})
    # 默认选中 = 度数最大的枢纽
    deg = senti_all("SELECT t, COUNT(*) c FROM (SELECT src_ticker t FROM funda_semi_edges UNION ALL SELECT dst_ticker t FROM funda_semi_edges) GROUP BY t ORDER BY c DESC LIMIT 1")
    default_tk = deg[0]["t"] if deg else (nodes[0]["ticker"] if nodes else "")
    dr = senti_one("SELECT MIN(trade_date) mn, MAX(trade_date) mx FROM senti_post") or {}
    return render_template("supplychain.html",
                           optlist=json.dumps(optlist, ensure_ascii=False), default_tk=default_tk,
                           tagmap=json.dumps(tagmap, ensure_ascii=False),
                           n_nodes=len(nodes), n_layers=n_layers,
                           n_senti=sum(1 for n in nodes if sdir.get(n["ticker"]) is not None),
                           senti_from=(dr.get("mn") or "—"), senti_to=(dr.get("mx") or "—"))


@app.route("/api/supplychain/node/<path:ticker>")
def supplychain_node(ticker):
    node = senti_one("SELECT ticker, name, layer, country FROM funda_semi_nodes WHERE ticker=?", (ticker,))
    if not node:
        return jsonify({"error": "not found"}), 404
    up = senti_all("""SELECT n.ticker, n.name, n.layer FROM funda_semi_edges e
        JOIN funda_semi_nodes n ON n.ticker=e.src_ticker
        WHERE e.dst_ticker=? AND e.relation='supply' ORDER BY n.layer LIMIT 150""", (ticker,))
    down = senti_all("""SELECT n.ticker, n.name, n.layer FROM funda_semi_edges e
        JOIN funda_semi_nodes n ON n.ticker=e.dst_ticker
        WHERE e.src_ticker=? AND e.relation='supply' ORDER BY n.layer LIMIT 150""", (ticker,))

    def both(rel):
        return senti_all(f"""SELECT DISTINCT n.ticker, n.name, n.layer FROM funda_semi_edges e
            JOIN funda_semi_nodes n ON n.ticker=(CASE WHEN e.src_ticker=? THEN e.dst_ticker ELSE e.src_ticker END)
            WHERE (e.src_ticker=? OR e.dst_ticker=?) AND e.relation='{rel}' LIMIT 120""", (ticker, ticker, ticker))
    comp = both("competitor"); part = both("partner")
    rmap = _name_map(); sdir = _supplychain_senti()

    def deco(items):
        for x in items:
            x["name"] = rmap.get(x["ticker"]) or rmap.get((x["ticker"] or "").split(".")[0]) or x["name"]
            d = sdir.get(x["ticker"])
            x["dir"] = round(d, 2) if d is not None else None
        return items

    def mean(items):
        ds = [x["dir"] for x in items if x["dir"] is not None]
        return round(sum(ds) / len(ds), 2) if ds else None
    up, down, comp, part = deco(up), deco(down), deco(comp), deco(part)
    d0 = sdir.get(ticker)
    node["dir"] = round(d0, 2) if d0 is not None else None
    node["name"] = rmap.get(ticker) or rmap.get((ticker or "").split(".")[0]) or node["name"]
    return jsonify({"node": node, "upstream": up, "downstream": down, "competitors": comp, "partners": part,
                    "counts": {"up": len(up), "down": len(down), "comp": len(comp), "part": len(part)},
                    "means": {"comp": mean(comp), "part": mean(part)}})


# ── main ─────────────────────────────────────────────
if __name__ == "__main__":
    log.info("Flask viewer 启动于 127.0.0.1:8080")
    app.run(host="127.0.0.1", port=8080, debug=False)
