from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, abort, current_app, g, has_request_context, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup, escape

try:
    import markdown as md_lib
except Exception:
    md_lib = None

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.opportunity_lens import read_models
from tools.opportunity_lens.api_models import envelope, error
from tools.opportunity_lens.constants import (
    DB_PATH,
    EARLY_SIGNAL_RULE_VERSION,
    EVIDENCE_POLICY_VERSION,
    EXPORT_ROOT,
    INTAKE_CONTRACT_VERSION,
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    RUN_PACK_SCHEMA_VERSION,
)
from tools.opportunity_lens.db import connect
from tools.opportunity_lens.export_pdf import create_pdf_export_job
from tools.opportunity_lens.intake_parser import parse_intake_payload
from tools.opportunity_lens.workflow import create_run
from tools.opportunity_lens.validators import ValidationError, validate_no_forbidden_public_fields
from tools.opportunity_lens.display_labels import CLIENT_DISPLAY_LABELS, COMMON_DISPLAY_LABELS

opportunity_lens_bp = Blueprint("opportunity_lens", __name__)

EVIDENCE_TOKEN_RE = re.compile(r"\^(?:evidence|src):([^\s\]\)<>，。；、,;^]+)")
BACKTICK_SOURCE_URI_RE = re.compile(r"`opp://source/(\d+)`")
NAKED_SOURCE_URI_RE = re.compile(r"(?<![\w:/^`])opp://source/(\d+)")
VISIBLE_SOURCE_REF_RE = re.compile(r"`?(?<!\^src:)(?<!\^evidence:)source_ref:[A-Za-z0-9_.-]+`?")

INTAKE_TEMPLATE_DIR = ROOT / "opportunity_lens" / "intake_templates"
INTAKE_REQUEST_DIR = ROOT / "opportunity_lens" / "intake_requests"


DISPLAY_LABELS = COMMON_DISPLAY_LABELS

# V2 公开页面需要把研究底稿中的状态码翻译成人能直接理解的中文。
# 这些映射刻意不写入 COMMON_DISPLAY_LABELS：旧 run 的兼容页面仍保持原合同，
# 新研究页面则不能把数据库枚举值暴露给读者。
V2_PUBLIC_LABELS = {
    "not_found_after_search": "检索后仍无直接数据",
    "stale_but_usable": "历史数据可用于背景，但时效有限",
    "historical_status_not_currently_verified": "仅有历史披露，当前进度待一手资料更新",
    "pending_current_update": "当前进度尚待一手资料更新",
    "PE_TTM": "滚动市盈率（PE-TTM）",
}

V2_PUBLIC_PHRASES = {
    "该指标槽尚未建立数据点级链接": "这个研究指标目前没有直接数据点支持",
    "指标槽": "研究指标",
}

_V2_PUBLIC_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(
        re.escape(key) for key in sorted(V2_PUBLIC_LABELS, key=len, reverse=True)
    ) + r")(?![A-Za-z0-9_])"
)


def _is_v2_request() -> bool:
    return has_request_context() and bool(getattr(g, "opp_viewer_v2", False))


def _humanize_v2_public_text(value) -> str:
    text = str(value or "")
    if not _is_v2_request() or not text:
        return text
    for source, replacement in V2_PUBLIC_PHRASES.items():
        text = text.replace(source, replacement)
    return _V2_PUBLIC_TOKEN_RE.sub(lambda match: V2_PUBLIC_LABELS[match.group(1)], text)


@opportunity_lens_bp.app_template_filter("opp_label")
def opp_label(value):
    if value is None:
        return "无"
    if _is_v2_request():
        return V2_PUBLIC_LABELS.get(str(value), DISPLAY_LABELS.get(str(value), value))
    return DISPLAY_LABELS.get(str(value), value)


@opportunity_lens_bp.app_template_filter("opp_public_text")
def opp_public_text(value):
    return _humanize_v2_public_text(value)


def _shorten_label(text: str, limit: int = 54) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


@lru_cache(maxsize=2048)
def _source_display_meta(source_id: int) -> tuple[str, str]:
    try:
        conn = connect(DB_PATH, readonly=True)
        row = conn.execute(
            """
            SELECT title, publisher, publish_date, source_tier
            FROM opportunity_source
            WHERE id=?
            """,
            (int(source_id),),
        ).fetchone()
        conn.close()
    except Exception:
        row = None
    if not row:
        return f"[源{source_id}]", f"来源 {source_id}"
    title = str(row["title"] or f"来源 {source_id}")
    tier = str(row["source_tier"] or "来源")
    publisher = str(row["publisher"] or "发布方未披露")
    publish_date = str(row["publish_date"] or "日期未披露")
    return f"[源{source_id}]", f"{title} · {publisher} · {publish_date} · {tier}级"


@lru_cache(maxsize=2048)
def _source_readable_meta(source_id: int) -> tuple[str, str]:
    try:
        conn = connect(DB_PATH, readonly=True)
        row = conn.execute(
            """
            SELECT title, publisher, publish_date, source_tier
            FROM opportunity_source
            WHERE id=?
            """,
            (int(source_id),),
        ).fetchone()
        conn.close()
    except Exception:
        row = None
    if not row:
        return f"来源 {source_id}", f"来源 {source_id}"
    title = str(row["title"] or f"来源 {source_id}").strip()
    publisher = str(row["publisher"] or "").strip()
    publish_date = str(row["publish_date"] or "").strip()
    tier = str(row["source_tier"] or "").strip()
    suffix_parts = [part for part in (publisher, publish_date) if part]
    label = _shorten_label(title, 72)
    if suffix_parts:
        label = f"{label}（{'，'.join(suffix_parts)}）"
    tooltip_parts = [title, publisher or "发布方未披露", publish_date or "日期未披露"]
    if tier:
        tooltip_parts.append(f"{tier}级来源")
    return label, " · ".join(tooltip_parts)


def _evidence_label(ref: str, *, title: bool = False) -> str:
    value = str(ref or "").strip()
    if not value:
        return "[来源]"
    numeric_source = re.match(r"^\d+$", value)
    if numeric_source:
        value = f"opp://source/{numeric_source.group(0)}"
    source_match = re.match(r"^opp://source/(\d+)$", value)
    if source_match:
        label, tooltip = _source_display_meta(int(source_match.group(1)))
        return tooltip if title else label
    patterns = [
        (r"^ab://research\.data_point/(\d+)$", "[{id}]"),
        (r"^ab://research\.source/(\d+)$", "[源{id}]"),
        (r"^opp://data_point/(\d+)$", "[点{id}]"),
        (r"^opp://factor_score/(\d+)$", "[因子{id}]"),
        (r"^opp://metric_slot/(\d+)$", "[指标{id}]"),
    ]
    for pattern, template in patterns:
        match = re.match(pattern, value)
        if match:
            return template.format(id=match.group(1))
    if value.startswith("http://") or value.startswith("https://"):
        return "[外部来源]"
    return "[证据]"


@opportunity_lens_bp.app_template_filter("opp_evidence_label")
def opp_evidence_label(value):
    return _evidence_label(value)


@opportunity_lens_bp.app_template_filter("opp_evidence_title")
def opp_evidence_title(value):
    return _evidence_label(value, title=True)


def _render_evidence_token(match: re.Match) -> str:
    ref = match.group(1)
    ref_value = f"opp://source/{ref}" if re.match(r"^\d+$", str(ref or "").strip()) else ref
    safe_ref = escape(ref_value)
    safe_label = escape(_evidence_label(ref_value))
    safe_title = escape(_evidence_label(ref_value, title=True))
    if has_request_context() and getattr(g, "opp_viewer_v2", False):
        return (
            '<button type="button" class="opp-src-ref" data-opp-evidence="'
            f'{safe_ref}" title="点击查看证据 {safe_title}" aria-label="查看证据 {safe_title}">'
            f"{safe_label}</button>"
        )
    return (
        '<sup class="opp-src-ref" data-opp-evidence="'
        f'{safe_ref}" tabindex="0" role="button" title="点击查看证据 {safe_title}">'
        f"{safe_label}</sup>"
    )


def _render_source_uri(match: re.Match) -> str:
    source_id = int(match.group(1))
    label, tooltip = _source_readable_meta(source_id)
    ref_value = f"opp://source/{source_id}"
    return (
        '<button type="button" class="opp-source-inline" data-opp-evidence="'
        f'{escape(ref_value)}" title="{escape(tooltip)}">{escape(label)}</button>'
    )


def _humanize_source_uris_for_display(value):
    if isinstance(value, str):
        return re.sub(
            r"opp://source/(\d+)",
            lambda match: _source_readable_meta(int(match.group(1)))[0],
            value,
        )
    if isinstance(value, list):
        return [_humanize_source_uris_for_display(item) for item in value]
    if isinstance(value, dict):
        return {key: _humanize_source_uris_for_display(item) for key, item in value.items()}
    return value


def _hide_visible_source_refs(text: str) -> str:
    return VISIBLE_SOURCE_REF_RE.sub("来源", str(text or ""))


@opportunity_lens_bp.app_template_filter("opp_display_json")
def opp_display_json(value):
    text = json.dumps(_humanize_source_uris_for_display(value), ensure_ascii=False, indent=2)
    return Markup(escape(text))


@opportunity_lens_bp.app_template_filter("opp_inline_evidence")
def opp_inline_evidence(value):
    text = str(value or "")
    if not text:
        return ""
    text = _hide_visible_source_refs(text)
    text = BACKTICK_SOURCE_URI_RE.sub(lambda match: f"^src:{match.group(1)}", text)
    text = NAKED_SOURCE_URI_RE.sub(lambda match: f"^src:{match.group(1)}", text)
    parts: list[str] = []
    last = 0
    for match in EVIDENCE_TOKEN_RE.finditer(text):
        parts.append(str(escape(_humanize_v2_public_text(text[last : match.start()]))))
        parts.append(_render_evidence_token(match))
        last = match.end()
    parts.append(str(escape(_humanize_v2_public_text(text[last:]))))
    return Markup("".join(parts))


def _classify_opp_tables(html: str) -> str:
    def classify(match: re.Match) -> str:
        table_html = match.group(0)
        classes = []
        if "交易操作框架" in table_html and ("监控信号" in table_html or "事件/监控信号" in table_html):
            classes.append("opp-monitor-table")
        if "关键监控信号" in table_html and "研究和交易响应" in table_html:
            classes.append("opp-followup-table")
        if "排名" in table_html and "核心分" in table_html:
            classes.append("opp-ranking-table")
        if "数据点数量" in table_html and ("独立 source_id" in table_html or "来源数量" in table_html):
            classes.append("opp-evidence-matrix-table")
        if ("标的类型" in table_html and "相对优先级" in table_html) or (
            "标的" in table_html and "同实体内比较" in table_html and "证实后动作" in table_html
        ):
            classes.append("opp-target-summary-table")
        if not classes:
            return table_html
        return table_html.replace("<table>", f'<table class="{" ".join(classes)}">', 1)

    return re.sub(r"<table>.*?</table>", classify, html, flags=re.S)


def _wrap_opp_tables(html: str) -> str:
    def wrap(match: re.Match) -> str:
        table_html = match.group(0)
        if "opp-wide-scroll" in table_html:
            return table_html
        return f'<div class="opp-wide-scroll opp-markdown-table-scroll">{table_html}</div>'

    return re.sub(r"<table\b.*?</table>", wrap, html, flags=re.S)


def _split_markdown_table_row(line: str) -> list[str] | None:
    if not line.strip().startswith("|") or not line.strip().endswith("|"):
        return None
    return [part.strip() for part in line.strip().strip("|").split("|")]


def _join_markdown_table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _normalize_monitor_tables(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    old_header = ["优先级", "监控信号", "证实/证伪条件", "预计变化/监控时间", "研究响应", "交易操作框架", "证据"]
    new_header = ["优先级", "事件/监控信号", "预计变化/监控时间", "证实/证伪条件", "研究响应", "交易操作框架", "证据"]
    order = [0, 1, 3, 2, 4, 5, 6]
    split_header = ["优先级", "监控信号", "证实条件", "证伪条件", "预计变化/监控时间", "研究响应", "交易操作框架", "证据"]
    split_new_header = ["优先级", "事件/监控信号", "预计变化/监控时间", "证实条件", "证伪条件", "研究响应", "交易操作框架", "证据"]
    split_order = [0, 1, 4, 2, 3, 5, 6, 7]
    while index < len(lines):
        cells = _split_markdown_table_row(lines[index])
        next_cells = _split_markdown_table_row(lines[index + 1]) if index + 1 < len(lines) else None
        if cells == split_header and next_cells and all(set(cell) <= {"-", ":"} for cell in next_cells):
            out.append(_join_markdown_table_row(split_new_header))
            out.append(lines[index + 1])
            index += 2
            while index < len(lines):
                row_cells = _split_markdown_table_row(lines[index])
                if not row_cells or len(row_cells) != len(split_order):
                    break
                out.append(_join_markdown_table_row([row_cells[i] for i in split_order]))
                index += 1
            continue
        if cells == old_header and next_cells and all(set(cell) <= {"-", ":"} for cell in next_cells):
            out.append(_join_markdown_table_row(new_header))
            out.append(lines[index + 1])
            index += 2
            while index < len(lines):
                row_cells = _split_markdown_table_row(lines[index])
                if not row_cells or len(row_cells) != len(order):
                    break
                out.append(_join_markdown_table_row([row_cells[i] for i in order]))
                index += 1
            continue
        if cells and cells[:2] == ["优先级", "监控信号"]:
            cells[1] = "事件/监控信号"
            out.append(_join_markdown_table_row(cells))
            index += 1
            continue
        out.append(lines[index])
        index += 1
    return "\n".join(out)


@opportunity_lens_bp.app_template_filter("opp_markdown")
def opp_markdown(value):
    text = str(value or "")
    if not text:
        return ""
    text = _humanize_v2_public_text(text)
    text = _normalize_monitor_tables(text)
    text = _hide_visible_source_refs(text)
    text = NAKED_SOURCE_URI_RE.sub(_render_source_uri, text)
    text = BACKTICK_SOURCE_URI_RE.sub(_render_source_uri, text)
    text = EVIDENCE_TOKEN_RE.sub(_render_evidence_token, text)
    if md_lib is None:
        return Markup("<pre>%s</pre>" % escape(text))
    html = md_lib.markdown(
        text,
        extensions=["extra", "sane_lists", "tables", "fenced_code"],
        output_format="html5",
    )
    html = _classify_opp_tables(html)
    html = _wrap_opp_tables(html)
    return Markup(html)


def _db_path():
    return current_app.config.get("OPPORTUNITY_LENS_DB_PATH", DB_PATH)


def _run_pack_schema_version(run_id: int) -> str:
    """Return the persisted pack schema that owns a rendered run.

    Legacy and V2 packs may need different data adapters/templates, but both must
    render the same public Opportunity Lens page family and information order.
    """

    conn = connect(_db_path(), readonly=True)
    try:
        row = conn.execute(
            """
            SELECT pack_schema_version
            FROM opportunity_run_manifest
            WHERE run_id=? AND pack_schema_version IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    return str(row["pack_schema_version"] or "") if row else ""


def _uses_v2_viewer(run_id: int | None) -> bool:
    return bool(run_id) and _run_pack_schema_version(int(run_id)) == RUN_PACK_SCHEMA_VERSION


def _entity_run_id(entity: dict) -> int | None:
    for key in ("maturation", "research_profile"):
        payload = entity.get(key)
        if isinstance(payload, dict) and payload.get("run_id"):
            return int(payload["run_id"])
    for key in ("sections", "data_points", "research_data_points", "investment_targets"):
        payload = entity.get(key)
        if isinstance(payload, list) and payload and payload[0].get("run_id"):
            return int(payload[0]["run_id"])
    return None


def _export_root():
    return current_app.config.get("OPPORTUNITY_LENS_EXPORT_ROOT", EXPORT_ROOT)


def _json(body_status):
    body, status = body_status
    return jsonify(body), status


def _render(template: str, **context):
    explicit_viewer_v2 = context.pop("_viewer_v2", None)
    g.opp_viewer_v2 = (
        template.endswith("_v2.html")
        if explicit_viewer_v2 is None
        else bool(explicit_viewer_v2)
    )
    context.setdefault("nav_active", "opportunity")
    context.setdefault("nav_world", "research")
    context.setdefault("opp_display_labels", CLIENT_DISPLAY_LABELS)
    return render_template(f"opportunity_lens/{template}", **context)


def _first_code_block(section: str, index: int = 0) -> str:
    blocks = re.findall(r"```(?:text|md)?\s*(.*?)```", section or "", flags=re.S)
    if index >= len(blocks):
        return ""
    return blocks[index].strip()


def _md_section(raw: str, title_keyword: str) -> str:
    pattern = rf"^##\s+.*?{re.escape(title_keyword)}.*?\n(.*?)(?=^---\s*$|^##\s+|\Z)"
    match = re.search(pattern, raw or "", flags=re.S | re.M)
    return match.group(1).strip() if match else ""


def _brief(text: str, limit: int = 150) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip("，,；;、:： ") + "。"


def _choice_label(choice: str, kind: str) -> str:
    value = (choice or "").strip().upper()
    if kind == "material":
        return {"A": "无资料", "B": "有研报或资料包", "C": "参考行研库行业"}.get(value, value or "未填写")
    return {"A": "时效优先", "B": "平衡", "C": "准确优先"}.get(value, value or "未填写")


INTAKE_EXAMPLE_FILES = (
    "Opportunity_Lens_研究请求_AI持仓拥挤度_深度补充版.md",
    "Opportunity_Lens_任务_AI高端电感行业研究与投资机会.md",
    "Opportunity_Lens_用户研究请求_硅片行业景气度_基于价格订单跟踪数据底座_修订版.md",
)


def _load_intake_examples() -> list[dict]:
    examples: list[dict] = []
    if not INTAKE_REQUEST_DIR.exists():
        return examples
    for filename in INTAKE_EXAMPLE_FILES:
        path = INTAKE_REQUEST_DIR / filename
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        material_section = _md_section(raw, "可用资料状态")
        policy_section = _md_section(raw, "证据策略")
        scope_section = _md_section(raw, "研究范围")
        constraints_section = _md_section(raw, "特殊约束")
        material_choice = _first_code_block(material_section, 0)
        policy_choice = _first_code_block(policy_section, 0)
        examples.append(
            {
                "title": path.stem.replace("Opportunity_Lens_", ""),
                "question": _brief(_first_code_block(_md_section(raw, "研究问题"), 0), 180),
                "material_choice": material_choice.strip().upper(),
                "material_label": _choice_label(material_choice, "material"),
                "material_detail": _brief(_first_code_block(material_section, 1) or _first_code_block(material_section, 2), 120),
                "policy_choice": policy_choice.strip().upper(),
                "policy_label": _choice_label(policy_choice, "policy"),
                "scope": _brief(_first_code_block(scope_section, 1) or _first_code_block(scope_section, 2) or _first_code_block(scope_section, 0), 140),
                "constraints": _brief(_first_code_block(constraints_section, 1) or _first_code_block(constraints_section, 0), 140),
                "raw_md": raw,
            }
        )
    return examples


@opportunity_lens_bp.route("/opportunity-lens")
def opportunity_home():
    runs = read_models.list_runs(limit=request.args.get("limit", 50), db_path=_db_path())
    return _render("index.html", runs=runs, health=read_models.health(db_path=_db_path()))


@opportunity_lens_bp.route("/opportunity-lens/request-generator")
def opportunity_request_generator():
    return _render(
        "request_generator.html",
        examples=_load_intake_examples(),
    )


@opportunity_lens_bp.route("/opportunity-lens/run/<int:run_id>")
def opportunity_run(run_id: int):
    run = read_models.get_run(run_id, db_path=_db_path())
    if not run:
        abort(404)
    return _render(
        "run_v2.html" if _uses_v2_viewer(run_id) else "run.html",
        run=run,
        entities=read_models.get_run_entities(run_id, db_path=_db_path()),
        visuals=read_models.get_visuals(run_id, db_path=_db_path()),
        rating_gap=read_models.get_run_rating_gap_summary(run_id, db_path=_db_path()),
    )


@opportunity_lens_bp.route("/opportunity-lens/run/<int:run_id>/entities")
def opportunity_entities(run_id: int):
    run = read_models.get_run(run_id, db_path=_db_path())
    if not run:
        abort(404)
    template = "entities_v2.html" if _uses_v2_viewer(run_id) else "entities.html"
    return _render(template, run=run, entities=read_models.get_run_entities(run_id, db_path=_db_path()))


@opportunity_lens_bp.route(
    "/opportunity-lens/run/<int:run_id>/entity-name/<path:entity_name>"
)
def opportunity_entity_by_name(run_id: int, entity_name: str):
    """Stable report link that resolves to the loader-assigned entity id."""

    entity = read_models.get_run_entity_by_name(
        run_id, entity_name, db_path=_db_path()
    )
    if not entity:
        abort(404)
    return redirect(
        url_for("opportunity_lens.opportunity_entity", entity_id=entity["entity_id"])
    )


@opportunity_lens_bp.route("/opportunity-lens/entity/<int:entity_id>")
def opportunity_entity(entity_id: int):
    entity = read_models.get_entity(entity_id, db_path=_db_path())
    if not entity:
        abort(404)
    template = "entity_v2.html" if _uses_v2_viewer(_entity_run_id(entity)) else "entity.html"
    return _render(template, entity=entity)


@opportunity_lens_bp.route("/opportunity-lens/target/<int:target_id>")
def opportunity_target(target_id: int):
    target = read_models.get_target(target_id, db_path=_db_path())
    if not target:
        abort(404)
    template = "target_v2.html" if _uses_v2_viewer(target.get("run_id")) else "target.html"
    return _render(template, target=target)


@opportunity_lens_bp.route("/opportunity-lens/factor/<int:factor_score_id>")
def opportunity_factor(factor_score_id: int):
    factor = read_models.get_factor(factor_score_id, db_path=_db_path())
    if not factor:
        abort(404)
    return _render(
        "factor_trace.html",
        factor=factor,
        _viewer_v2=_uses_v2_viewer(factor.get("run_id")),
    )


@opportunity_lens_bp.route("/opportunity-lens/metric-slot/<int:slot_id>")
def opportunity_metric_slot(slot_id: int):
    slot = read_models.get_metric_slot(slot_id, db_path=_db_path())
    if not slot:
        abort(404)
    return _render(
        "metric_slot_trace.html",
        slot=slot,
        _viewer_v2=_uses_v2_viewer(slot.get("run_id")),
    )


@opportunity_lens_bp.route("/opportunity-lens/run/<int:run_id>/audit")
def opportunity_audit(run_id: int):
    run = read_models.get_run(run_id, db_path=_db_path())
    if not run:
        abort(404)
    return _render(
        "audit.html",
        run=run,
        board=read_models.get_audit_board(run_id, db_path=_db_path()),
        _viewer_v2=_uses_v2_viewer(run_id),
    )


@opportunity_lens_bp.route("/opportunity-lens/run/<int:run_id>/supplement")
def opportunity_supplement(run_id: int):
    run = read_models.get_run(run_id, db_path=_db_path())
    if not run:
        abort(404)
    return _render(
        "supplement.html",
        run=run,
        requests=read_models.get_supplement_requests(run_id, db_path=_db_path()),
        _viewer_v2=_uses_v2_viewer(run_id),
    )


@opportunity_lens_bp.route("/opportunity-lens/run/<int:run_id>/export")
def opportunity_export(run_id: int):
    run = read_models.get_run(run_id, db_path=_db_path())
    if not run:
        abort(404)
    return _render(
        "export.html",
        run=run,
        export_status=read_models.get_export_status(run_id, db_path=_db_path()),
        _viewer_v2=_uses_v2_viewer(run_id),
    )


@opportunity_lens_bp.route("/api/opportunity-lens/health")
def api_health():
    return _json(envelope(read_models.health(db_path=_db_path())))


@opportunity_lens_bp.route("/api/opportunity-lens/runs")
def api_runs():
    return _json(envelope(read_models.list_runs(limit=request.args.get("limit", 50), status=request.args.get("status"), db_path=_db_path())))


@opportunity_lens_bp.route("/api/opportunity-lens/run", methods=["POST"])
def api_create_run():
    idempotency_key = request.headers.get("X-Idempotency-Key")
    actor = request.headers.get("X-Actor") or request.headers.get("X-Reviewer")
    reason = request.headers.get("X-Reason")
    if not idempotency_key or not actor or not reason:
        return _json(error("OPP_BAD_REQUEST", "创建扫描必须提供 X-Idempotency-Key、X-Actor、X-Reason", 400))
    payload = request.get_json(silent=True) or {}
    try:
        validate_no_forbidden_public_fields(payload)
        intake = parse_intake_payload(payload)
    except (ValidationError, ValueError) as exc:
        return _json(error("OPP_BAD_REQUEST", str(exc), 400))
    conn = connect(_db_path())
    try:
        existing = conn.execute(
            """
            SELECT run_id FROM opportunity_run_manifest
            WHERE manifest_type='run_creation_request' AND manifest_hash=?
            ORDER BY id LIMIT 1
            """,
            (f"idempotency:{idempotency_key}",),
        ).fetchone()
        if existing:
            conn.rollback()
            return _json(envelope(read_models.get_run(existing["run_id"], db_path=_db_path()), status=200))
        run_id = create_run(
            conn,
            research_question=intake["research_question"],
            requested_by=actor,
            problem_statement=payload.get("problem_statement"),
            display_title=payload.get("display_title"),
            available_materials_choice=intake["available_materials_choice"],
            evidence_policy=intake["evidence_policy"],
            intake_contract_payload=intake,
        )
        conn.execute(
            """
            INSERT INTO opportunity_run_manifest(
              run_id, manifest_type, manifest_json, manifest_hash,
              intake_contract_version, evidence_policy_version, early_signal_rule_version,
              workflow_contract_version, pack_schema_version
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                "run_creation_request",
                json.dumps({"actor": actor, "reason": reason}, ensure_ascii=False, sort_keys=True),
                f"idempotency:{idempotency_key}",
                INTAKE_CONTRACT_VERSION,
                EVIDENCE_POLICY_VERSION,
                EARLY_SIGNAL_RULE_VERSION,
                RESEARCH_WORKFLOW_CONTRACT_VERSION,
                RUN_PACK_SCHEMA_VERSION,
            ),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return _json(error("OPP_CREATE_FAILED", str(exc), 500))
    finally:
        conn.close()
    return _json(envelope(read_models.get_run(run_id, db_path=_db_path()), status=201))


@opportunity_lens_bp.route("/api/opportunity-lens/run/<int:run_id>")
def api_run(run_id: int):
    run = read_models.get_run(run_id, db_path=_db_path())
    if not run:
        return _json(error("OPP_NOT_FOUND", f"扫描任务 {run_id} 不存在", 404))
    return _json(envelope(run))


@opportunity_lens_bp.route("/api/opportunity-lens/run/<int:run_id>/intake")
def api_intake(run_id: int):
    intake = read_models.get_intake_contract(run_id, db_path=_db_path())
    if not intake:
        return _json(error("OPP_NOT_FOUND", f"扫描任务 {run_id} 暂无 intake contract", 404))
    return _json(envelope(intake))


@opportunity_lens_bp.route("/api/opportunity-lens/run/<int:run_id>/early-signals")
def api_early_signals(run_id: int):
    return _json(envelope(read_models.get_early_signals(run_id, db_path=_db_path())))


@opportunity_lens_bp.route("/api/opportunity-lens/run/<int:run_id>/sections")
def api_sections(run_id: int):
    return _json(envelope(read_models.get_sections(run_id, db_path=_db_path())))


@opportunity_lens_bp.route("/api/opportunity-lens/run/<int:run_id>/entities")
def api_entities(run_id: int):
    return _json(envelope(read_models.get_run_entities(run_id, limit=request.args.get("limit", 100), db_path=_db_path())))


@opportunity_lens_bp.route("/api/opportunity-lens/entity/<int:entity_id>")
def api_entity(entity_id: int):
    entity = read_models.get_entity(entity_id, db_path=_db_path())
    if not entity:
        return _json(error("OPP_NOT_FOUND", f"实体 {entity_id} 不存在", 404))
    return _json(envelope(entity))


@opportunity_lens_bp.route("/api/opportunity-lens/target/<int:target_id>")
def api_target(target_id: int):
    target = read_models.get_target(target_id, db_path=_db_path())
    if not target:
        return _json(error("OPP_NOT_FOUND", f"标的 {target_id} 不存在", 404))
    return _json(envelope(target))


@opportunity_lens_bp.route("/api/opportunity-lens/entity/<int:entity_id>/score")
def api_entity_score(entity_id: int):
    score = read_models.get_score(entity_id, score_batch_id=request.args.get("score_batch_id"), db_path=_db_path())
    if not score:
        return _json(error("OPP_NOT_FOUND", f"实体 {entity_id} 暂无评分", 404))
    return _json(envelope(score))


@opportunity_lens_bp.route("/api/opportunity-lens/factor/<int:factor_score_id>/trace")
def api_factor_trace(factor_score_id: int):
    factor = read_models.get_factor(factor_score_id, db_path=_db_path())
    if not factor:
        return _json(error("OPP_NOT_FOUND", f"因子评分 {factor_score_id} 不存在", 404))
    return _json(envelope(factor))


@opportunity_lens_bp.route("/api/opportunity-lens/metric-slot/<int:slot_id>/trace")
def api_metric_slot_trace(slot_id: int):
    slot = read_models.get_metric_slot(slot_id, db_path=_db_path())
    if not slot:
        return _json(error("OPP_NOT_FOUND", f"指标槽 {slot_id} 不存在", 404))
    return _json(envelope(slot))


@opportunity_lens_bp.route("/api/opportunity-lens/evidence/resolve")
def api_evidence_resolve():
    ref = request.args.get("ref")
    if not ref:
        return _json(error("OPP_BAD_REQUEST", "缺少 ref 查询参数", 400))
    try:
        return _json(envelope(read_models.resolve_evidence(ref, db_path=_db_path())))
    except ValidationError as exc:
        return _json(error("OPP_BAD_URI", str(exc), 400))


@opportunity_lens_bp.route("/api/opportunity-lens/run/<int:run_id>/audit")
def api_audit(run_id: int):
    return _json(envelope(read_models.get_audit_board(run_id, db_path=_db_path())))


@opportunity_lens_bp.route("/api/opportunity-lens/run/<int:run_id>/supplement-requests")
def api_supplement(run_id: int):
    return _json(envelope(read_models.get_supplement_requests(run_id, db_path=_db_path())))


@opportunity_lens_bp.route("/api/opportunity-lens/run/<int:run_id>/visuals")
def api_visuals(run_id: int):
    return _json(envelope(read_models.get_visuals(run_id, db_path=_db_path())))


@opportunity_lens_bp.route("/api/opportunity-lens/export/<int:run_id>/status")
def api_export_status(run_id: int):
    return _json(envelope(read_models.get_export_status(run_id, job_id=request.args.get("job_id", "latest"), db_path=_db_path())))


@opportunity_lens_bp.route("/api/opportunity-lens/run/<int:run_id>/export-pdf", methods=["POST"])
def api_export_pdf(run_id: int):
    job_id = create_pdf_export_job(
        run_id,
        requested_by=request.headers.get("X-Reviewer", "manual"),
        db_path=_db_path(),
        export_root=_export_root(),
    )
    return _json(envelope(read_models.get_export_status(run_id, job_id=job_id, db_path=_db_path()), status=202))
