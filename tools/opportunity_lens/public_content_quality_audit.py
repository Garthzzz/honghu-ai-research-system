from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "opportunity_lens.public_content_quality_audit.v2"
PUBLIC_AUDIT_FIELD = "_public_content_quality_audit"
PUBLIC_AUDIT_MANIFEST_TYPE = "public_content_quality_audit"
_HASH_PREFIX = "sha256:"


@dataclass(frozen=True)
class AuditIssue:
    severity: str
    code: str
    artifact: str
    scope: str
    line: int | None
    message: str
    excerpt: str = ""
    count: int = 1


@dataclass(frozen=True)
class MarkdownTable:
    artifact: str
    scope: str
    start_line: int
    end_line: int
    heading: str
    headers: tuple[str, ...]
    separator: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    @property
    def context(self) -> str:
        return " ".join((self.scope, self.heading, *self.headers))


@dataclass
class ScopeAudit:
    issues: list[AuditIssue]
    tables: list[MarkdownTable]


_CITATION_TOKEN_RE = re.compile(
    r"\^(?:src|evidence):(?:source_ref:)?[A-Za-z0-9_.:/-]+", re.IGNORECASE
)
_MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\((?:https?://|mailto:)[^)]+\)")
_MARKDOWN_REFERENCE_RE = re.compile(r"(?m)^(\s*\[[^\]]+\]:)\s*(?:https?://|mailto:)\S+.*$")
_BARE_URL_RE = re.compile(r"(?<!\]\()(?<!href=[\"'])(?<!src=[\"'])https?://[^\s)>]+", re.IGNORECASE)
_WINDOWS_PATH_RE = re.compile(r"(?<![\w])(?:[A-Za-z]:[\\/])(?:[^\s`|<>]+)")
_PROJECT_PATH_RE = re.compile(
    r"(?<![\w])(?:cache|data|tools|opportunity_lens|papers|config|archive)/"
    r"[^\s`|<>]+",
    re.IGNORECASE,
)
_JSON_FENCE_RE = re.compile(r"```\s*json\b", re.IGNORECASE)
_JSON_LINE_RE = re.compile(r"(?m)^\s*(?:\{\s*\"[^\"]+\"\s*:|\[\s*\{\s*\"[^\"]+\"\s*:)")
_RAW_FORMULA_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "formula_source_assignment",
        re.compile(r"\$(?:center|half|low|mode|high|[A-Za-z]+_[A-Za-z_]*)\s*=.*?\$", re.IGNORECASE),
        "公式仍是美元符号包裹的变量赋值源码，应改成可渲染公式或中文算式。",
    ),
    (
        "formula_programming_expression",
        re.compile(r"(?<!\w)(?:numpy\.|np\.|math\.|lambda\s+\w+|\w+\s*\*\*\s*\w+|conditional_on_[a-z_]+)"),
        "正文出现编程表达式或内部变量名，没有完成面向读者的转译。",
    ),
)
_RAW_TEX_COMMAND_RE = re.compile(r"\\(?:sqrt|frac|pm|left|right|begin|end)\b")


# 这些规则适用于所有公开输出。生产字段本身可以留在 pack，但其值不能泄露到
# 标题、正文、标的建议、可视化说明等公开表面。
_BASE_PUBLIC_TERM_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("machine_term_canonical", re.compile(r"\bcanonical\b", re.IGNORECASE), "公开正文出现生产术语 canonical。"),
    ("machine_term_intake", re.compile(r"\bintake\b", re.IGNORECASE), "公开正文出现生产术语 intake。"),
    ("machine_term_field_completion", re.compile(r"字段(?:完成(?:情况|状态|度|矩阵)?|覆盖(?:率|情况)?|逐项完成)"), "公开正文出现字段完成或覆盖审计语言。"),
    ("machine_term_output_coverage", re.compile(r"输出覆盖卡|结构化财务快照完成度|经营字段逐项完成矩阵"), "公开正文出现输出覆盖或完成矩阵。"),
    ("machine_term_parameter_owner", re.compile(r"参数\s*(?:owner|归属|负责人)", re.IGNORECASE), "公开正文出现参数归属字段。"),
    ("machine_term_proxy", re.compile(r"本轮代理|受影响参数"), "公开正文出现内部代理或受影响参数字段。"),
    (
        "machine_term_freshness_code",
        re.compile(
            r"\b(?:SEVERE_OLD_FOR_CURRENT_JUDGMENT|"
            r"2024_RECORD_NEEDS_CURRENT_PRODUCT_CORROBORATION|"
            r"SEVERE_FRESHNESS_WARNING)\b"
        ),
        "公开时效提醒暴露机器代码，应改成说明资料年份、可证明内容和不能证明内容的完整中文。",
    ),
    (
        "machine_term_raw_date_enum",
        re.compile(
            r"(?:current_at_(?:fetch|access)|current_page|"
            r"\d{4}-(?:spring|campus-cycle)|\d{4}-campus-cycle|"
            r"\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2})",
            re.IGNORECASE,
        ),
        "公开内容暴露机器日期枚举，应改成自然中文日期或招聘周期。",
    ),
    ("machine_term_debt_code", re.compile(r"(?<![A-Za-z0-9])D[012](?![A-Za-z0-9])|D0\s*/\s*D1\s*/\s*D2", re.IGNORECASE), "公开正文出现 D0/D1/D2 内部代码。"),
    ("machine_term_scenario_code", re.compile(r"A\s*[—–-]\s*F|(?:情景|路径|架构)\s*[A-G](?![A-Za-z])", re.IGNORECASE), "公开正文要求读者记忆 A—F/G 情景代码。"),
    ("machine_term_architecture_code", re.compile(r"(?<![A-Za-z])P\s*/\s*H\s*/\s*C(?![A-Za-z])", re.IGNORECASE), "公开正文出现 P/H/C 内部架构代码。"),
    ("machine_term_triangular_fields", re.compile(r"\blow\s*/\s*mode\s*/\s*high\b|后验三角|三角\s*(?:low|mode|high)", re.IGNORECASE), "公开正文出现 low/mode/high 内部概率参数。"),
    ("bad_label_section_boundary", re.compile(r"本节结论状态与专属边界|本节专属缺口"), "公开正文仍使用机器化的章节状态或专属边界标签。"),
    ("bad_label_decision_meaning", re.compile(r"决策含义"), "公开正文仍使用缺少主语的“决策含义”标签。"),
    ("bad_label_next_update", re.compile(r"下一次更新"), "不要用机械更新标签；应在当前问题的分析中直接说明监控指标、证伪条件或资料限制。"),
    ("deprecated_follow_up_section", re.compile(r"如果想进一步研究[，,：:\s]*(?:需要)?补充(?:的信息)?"), "该标准栏目已取消；数据限制应写回当前问题的分析，不能用后续清单替代本轮回答。"),
    ("bad_label_minimum_proof", re.compile(r"最低可证含义|不可推出"), "公开正文仍使用证据审计台账语言。"),
    ("bad_label_damage", re.compile(r"破坏程度|破坏度|专家压力带"), "公开正文使用了主体和影响不清楚的抽象标签。"),
    ("bad_label_unknown", re.compile(r"\[\s*(?:\*\*)?未知(?:\*\*)?\s*\]|\*\*未知\*\*"), "不得用“未知”作为机械状态标签，应说明没有直接证据、资料不足或无法推断。"),
    ("raw_internal_uri", re.compile(r"opp://|(?:source|evidence)_ref_uri|\bsource_id\s*:", re.IGNORECASE), "公开正文暴露内部 URI 或内部证据字段。"),
    ("raw_source_ref", re.compile(r"(?<!\^src:)\bsource_ref\s*:", re.IGNORECASE), "公开正文暴露 source_ref 字段。"),
)


# 这些词在别的研究中可能是经过解释后仍有用的统计或展示术语；只对本次
# “比亚迪与立讯进入高速光模块”专题执行严格禁用，避免 generic 审计误伤。
_BYD_LUXSHARE_TERM_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("machine_term_quantile", re.compile(r"(?<![A-Za-z0-9])P(?:10|90)(?![A-Za-z0-9])", re.IGNORECASE), "本专题公开正文不展示 P10/P90，应直接给出可理解的中心判断和范围。"),
    ("machine_term_wilson", re.compile(r"Wilson(?:区间|置信区间)?", re.IGNORECASE), "本专题案例不满足同质随机样本前提，公开正文不得用 Wilson 区间包装判断。"),
    ("machine_term_frechet", re.compile(r"Fr[ée]chet", re.IGNORECASE), "本专题公开正文不展示 Fréchet 内部依赖术语。"),
    ("bad_label_baseline_path", re.compile(r"基线路径|基线情景"), "本专题应直接写具体情景与假设，不使用含义不清的“基线路径/基线情景”。"),
    ("bad_label_marginal_probability", re.compile(r"边际概率"), "本专题应直接写清公司、市场和期限，不使用“边际概率”。"),
    ("bad_label_architecture_status", re.compile(r"架构状态"), "本专题应直接写完整中文情景，不使用“架构状态”。"),
    ("bad_label_dashboard", re.compile(r"\bdashboard\b", re.IGNORECASE), "本专题应使用自然中文名称，不暴露 dashboard 生产标签。"),
    ("bad_label_working_prior_mode", re.compile(r"工作先验(?:的)?众数|工作先验"), "本专题不展示统计依据不足且读者难以理解的“工作先验”。"),
)


_PUBLIC_TOP_LEVEL_FIELDS = (
    "display_title",
    "research_question",
    "problem_statement",
    "gap_summary",
)
_PUBLIC_ENTITY_FIELDS = ("display_name", "canonical_name", "description")
_PUBLIC_SOURCE_FIELDS = ("freshness_warning",)
_PUBLIC_PROFILE_FIELDS = (
    "research_question",
    "research_scope",
    "methodology_note",
    "literature_review_markdown",
    "analysis_markdown",
    "answer_markdown",
    "conclusion_markdown",
    "limitations_markdown",
)
_PUBLIC_TARGET_FIELDS = (
    "target_name",
    "exposure_rationale",
    "research_action",
    "investment_view",
    "risk_note",
    "target_quality_label",
    "relative_preference",
    "confirmed_scenario_action",
    "falsified_scenario_action",
    "target_profile_markdown",
    "target_deep_research_markdown",
    "entity_relation_markdown",
    "parent_research_relation_markdown",
    "conditional_investment_recommendation",
    "financial_data_status",
)
_PUBLIC_TARGET_POINT_FIELDS = (
    "metric_name",
    "period",
    "as_of_date",
    "value_text",
    "unit",
    "source_title",
    "source_title_zh",
    "source_publisher",
    "source_excerpt",
    "source_excerpt_zh",
    "data_quality_label",
    "direction",
)
_PUBLIC_VISUAL_FIELDS = (
    "title",
    "subtitle",
    "how_to_read",
    "caption",
    "note",
    "notes",
    "method_note",
    "source_note",
    "empty_state_reason",
)
_PUBLIC_NAV_FIELDS = ("label", "title")
_PUBLIC_SUPPLEMENT_FIELDS = (
    "request_title",
    "request_detail",
    "gap_title",
    "why_needed",
    "expected_use",
    "request_text",
)
_VISUAL_VISIBLE_KEY_RE = re.compile(
    r"(?:title|label|name|note|description|explanation|caption|text|value_text|unit|period|series|category|scenario)",
    re.IGNORECASE,
)
_VISUAL_HIDDEN_KEY_RE = re.compile(r"(?:ref|uri|url|path|key|id|hash)", re.IGNORECASE)
_LONG_PARAGRAPH_MIN_CHARS = 160
_USER_QUESTION_SAFETY_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("bare_url", _BARE_URL_RE, "原始研究请求包含裸 URL；应改为有标题的链接或附件说明。"),
    ("disk_path", _WINDOWS_PATH_RE, "原始研究请求暴露 Windows 磁盘路径。"),
    ("project_path", _PROJECT_PATH_RE, "原始研究请求暴露项目内部路径。"),
    ("raw_internal_uri", re.compile(r"opp://|(?:source|evidence)_ref_uri|\bsource_id\s*:", re.IGNORECASE), "原始研究请求暴露内部 URI。"),
    ("raw_source_ref", re.compile(r"(?<!\^src:)\bsource_ref\s*:", re.IGNORECASE), "原始研究请求暴露内部 source_ref。"),
    ("raw_json", _JSON_FENCE_RE, "原始研究请求包含原始 JSON 代码块。"),
    ("raw_json", _JSON_LINE_RE, "原始研究请求包含疑似原始 JSON 对象。"),
)


_QUESTION_CUES = re.compile(r"[？?]|(?:要回答|问题(?:是|在于)|需要判断|核心(?:问题|是)|能否|是否|为什么|如何|会怎样|有多大)")
_EVIDENCE_CUES = re.compile(r"(?:证据|数据|年报|财报|公告|披露|公开资料|产品页|规格书|记录|来源|显示|表明)")
_ANALYSIS_CUES = re.compile(r"(?:分析|结论|因此|所以|这意味着|可以认为|我们认为|当前判断|综合来看|更可能|不足以支持)")
_METHOD_CUES = re.compile(r"(?:方法|计算|估算|测算|加权|输入|假设|先.+再|按照.+得到|以.+作为|敏感性)")
_CALCULATION_TOPIC = re.compile(r"(?:概率|财务|盈利|估值|终值|市场规模|供需模型|供给模型|需求模型|预测|估算|测算|敏感性|202[7-9].{0,12}203[01])")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _HASH_PREFIX + hashlib.sha256(encoded).hexdigest()


def _pack_without_runtime_fields(pack: dict[str, Any]) -> dict[str, Any]:
    """Return the authored pack content used by the public-audit binding hash.

    The attestation and loader-only fields are excluded to avoid a recursive hash and
    to make the builder and loader calculate the same digest.
    """

    return {
        key: value
        for key, value in pack.items()
        if key not in {PUBLIC_AUDIT_FIELD, "_pack_path", "_contract_validation_report"}
    }


def public_pack_hash(pack: dict[str, Any]) -> str:
    return _hash_json(_pack_without_runtime_fields(pack))


def _effective_term_rules(target_profile: bool) -> tuple[tuple[str, re.Pattern[str], str], ...]:
    if target_profile:
        return _BASE_PUBLIC_TERM_RULES + _BYD_LUXSHARE_TERM_RULES
    return _BASE_PUBLIC_TERM_RULES


def _rules_hash(*, target_profile: bool) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "profile": "byd_luxshare" if target_profile else "generic",
        "term_rules": [
            {"code": code, "pattern": pattern.pattern, "flags": pattern.flags, "message": message}
            for code, pattern, message in _effective_term_rules(target_profile)
        ],
        "formula_rules": [
            {"code": code, "pattern": pattern.pattern, "flags": pattern.flags, "message": message}
            for code, pattern, message in _RAW_FORMULA_PATTERNS
        ],
        "user_question_safety_rules": [
            {"code": code, "pattern": pattern.pattern, "flags": pattern.flags, "message": message}
            for code, pattern, message in _USER_QUESTION_SAFETY_RULES
        ],
        "public_surfaces": {
            "top_level": _PUBLIC_TOP_LEVEL_FIELDS,
            "entity": _PUBLIC_ENTITY_FIELDS,
            "source": _PUBLIC_SOURCE_FIELDS,
            "profile": _PUBLIC_PROFILE_FIELDS,
            "target": _PUBLIC_TARGET_FIELDS,
            "target_point": _PUBLIC_TARGET_POINT_FIELDS,
            "visual": _PUBLIC_VISUAL_FIELDS,
            "nav": _PUBLIC_NAV_FIELDS,
            "supplement": _PUBLIC_SUPPLEMENT_FIELDS,
        },
            "structure": {
                "question": _QUESTION_CUES.pattern,
                "evidence": _EVIDENCE_CUES.pattern,
                "analysis": _ANALYSIS_CUES.pattern,
                "data_limits": "limitations_must_be_explained_inside_current_analysis_not_deferred_section",
                "method": _METHOD_CUES.pattern,
                "calculation_topic": _CALCULATION_TOPIC.pattern,
            },
        "limits": {
            "target_probability_tables": 2,
            "target_finance_tables": 3,
            "entity_tables": 3,
            "last_column_chars": 140,
            "long_paragraph_chars": _LONG_PARAGRAPH_MIN_CHARS,
        },
        "composition_policy": {
            "final_report": "main_sections_only_entity_pages_are_separate",
            "finance_sensitivity": "one_quantified_table_or_quantified_prose",
            "low_information_tables": "delete_or_merge",
        },
    }
    return _hash_json(payload)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _excerpt(text: str, offset: int, length: int = 120) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end < 0:
        end = len(text)
    value = re.sub(r"\s+", " ", text[start:end]).strip()
    return value[:length]


def _visible_text(text: str) -> str:
    text = _CITATION_TOKEN_RE.sub("", text)
    text = _MARKDOWN_LINK_RE.sub(lambda match: match.group(1), text)
    text = _MARKDOWN_REFERENCE_RE.sub(lambda match: match.group(1), text)
    return text


def _normalized_cell(value: str) -> str:
    value = _visible_text(value)
    value = re.sub(r"[`*_~]", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def _split_markdown_row(line: str) -> tuple[str, ...]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith(r"\|"):
        value = value[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    in_code = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char == "`":
            in_code = not in_code
            current.append(char)
            continue
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return tuple(cells)


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _is_separator(cells: Iterable[str]) -> bool:
    cells = tuple(cells)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def parse_markdown_tables(
    text: str,
    *,
    artifact: str,
    scope: str,
    default_heading: str | None = None,
) -> list[MarkdownTable]:
    lines = text.splitlines()
    tables: list[MarkdownTable] = []
    heading = default_heading or scope
    index = 0
    while index < len(lines):
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", lines[index])
        if heading_match:
            heading = heading_match.group(1).strip()
        if index + 1 >= len(lines) or not _is_table_row(lines[index]):
            index += 1
            continue
        header = _split_markdown_row(lines[index])
        separator = _split_markdown_row(lines[index + 1]) if _is_table_row(lines[index + 1]) else ()
        if not _is_separator(separator):
            index += 1
            continue
        rows: list[tuple[str, ...]] = []
        cursor = index + 2
        while cursor < len(lines) and _is_table_row(lines[cursor]):
            rows.append(_split_markdown_row(lines[cursor]))
            cursor += 1
        tables.append(
            MarkdownTable(
                artifact=artifact,
                scope=scope,
                start_line=index + 1,
                end_line=cursor,
                heading=heading,
                headers=header,
                separator=separator,
                rows=tuple(rows),
            )
        )
        index = cursor
    return tables


def _aggregate_pattern_issue(
    issues: list[AuditIssue],
    *,
    pattern: re.Pattern[str],
    code: str,
    message: str,
    text: str,
    artifact: str,
    scope: str,
) -> None:
    matches = list(pattern.finditer(text))
    if not matches:
        return
    first = matches[0]
    issues.append(
        AuditIssue(
            severity="error",
            code=code,
            artifact=artifact,
            scope=scope,
            line=_line_number(text, first.start()),
            message=message,
            excerpt=_excerpt(text, first.start()),
            count=len(matches),
        )
    )


def _audit_tables(tables: list[MarkdownTable]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    seen_headers: dict[tuple[str, ...], MarkdownTable] = {}
    seen_rows: dict[tuple[str, ...], tuple[MarkdownTable, int]] = {}
    for table in tables:
        expected = len(table.headers)
        if expected < 2 or any(not _normalized_cell(cell) for cell in table.headers):
            issues.append(AuditIssue("error", "table_header_invalid", table.artifact, table.scope, table.start_line, "表头存在空列或列数不足。", " | ".join(table.headers)))
        if not table.rows:
            issues.append(AuditIssue("error", "table_without_data", table.artifact, table.scope, table.start_line, "表格只有表头而没有数据，应删除空表或补齐数据。", " | ".join(table.headers)))
        if len(table.separator) != expected:
            issues.append(AuditIssue("error", "table_column_count_mismatch", table.artifact, table.scope, table.start_line + 1, f"表格分隔行有 {len(table.separator)} 列，表头有 {expected} 列。"))
        header_signature = tuple(_normalized_cell(cell) for cell in table.headers)
        if len(set(header_signature)) != len(header_signature):
            issues.append(AuditIssue("error", "table_duplicate_column", table.artifact, table.scope, table.start_line, "同一表格存在重复列名。", " | ".join(table.headers)))
        if header_signature in seen_headers:
            previous = seen_headers[header_signature]
            issues.append(AuditIssue("error", "table_duplicate_header", table.artifact, table.scope, table.start_line, f"该表头与同一公开文档第 {previous.start_line} 行的表格重复；应合并或删除低信息表。", " | ".join(table.headers)))
        else:
            seen_headers[header_signature] = table
        local_rows: dict[tuple[str, ...], int] = {}
        for offset, row in enumerate(table.rows, start=2):
            line = table.start_line + offset
            if len(row) != expected:
                issues.append(AuditIssue("error", "table_column_count_mismatch", table.artifact, table.scope, line, f"该行有 {len(row)} 列，表头有 {expected} 列。", " | ".join(row)))
                continue
            signature = tuple(_normalized_cell(cell) for cell in row)
            if not any(signature):
                issues.append(AuditIssue("error", "table_empty_row", table.artifact, table.scope, line, "表格包含空行。"))
                continue
            if signature in local_rows:
                issues.append(AuditIssue("error", "table_duplicate_row", table.artifact, table.scope, line, f"该行与本表第 {local_rows[signature]} 行完全重复。", " | ".join(row)))
            else:
                local_rows[signature] = line
            if signature in seen_rows:
                previous_table, previous_line = seen_rows[signature]
                if previous_table is not table:
                    issues.append(AuditIssue("error", "table_duplicate_row_across_tables", table.artifact, table.scope, line, f"该行与同一公开文档第 {previous_line} 行重复；请检查表格是否重叠。", " | ".join(row)))
            else:
                seen_rows[signature] = (table, line)
            if len(row) == expected and len(_visible_text(row[-1]).strip()) > 140:
                issues.append(
                    AuditIssue(
                        "error",
                        "table_last_column_prose_overload",
                        table.artifact,
                        table.scope,
                        line,
                        "表格最后一列承载了整段分析；请把复杂判断移到表后正文，只保留可横向比较的短句。",
                        _visible_text(row[-1]).strip()[:140],
                    )
                )
    return issues


def _cross_table_duplicate_issues(tables: list[MarkdownTable], *, artifact: str) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    seen_headers: dict[tuple[str, ...], MarkdownTable] = {}
    seen_rows: dict[tuple[str, ...], tuple[MarkdownTable, int]] = {}
    for table in tables:
        header = tuple(_normalized_cell(cell) for cell in table.headers)
        previous_header = seen_headers.get(header)
        if previous_header is not None and previous_header.scope != table.scope:
            issues.append(
                AuditIssue(
                    "error",
                    "table_duplicate_header_across_sections",
                    artifact,
                    table.scope,
                    table.start_line,
                    f"该表头与章节 {previous_header.scope} 的表格重复；应确认两表是否回答同一问题并合并。",
                    " | ".join(table.headers),
                )
            )
        else:
            seen_headers[header] = table
        for offset, row in enumerate(table.rows, start=2):
            signature = tuple(_normalized_cell(cell) for cell in row)
            previous_row = seen_rows.get(signature)
            if previous_row is not None and previous_row[0].scope != table.scope:
                issues.append(
                    AuditIssue(
                        "error",
                        "table_duplicate_row_across_sections",
                        artifact,
                        table.scope,
                        table.start_line + offset,
                        f"该行与章节 {previous_row[0].scope} 第 {previous_row[1]} 行重复；请删除重复信息。",
                        " | ".join(row),
                    )
                )
            else:
                seen_rows[signature] = (table, table.start_line + offset)
    return issues


def _structure_issues(
    text: str,
    *,
    artifact: str,
    scope: str,
    title: str,
    role: str,
) -> list[AuditIssue]:
    if re.search(r"(?:来源索引|参考文献|证据索引|附录)", title):
        return []
    visible = _visible_text(text)
    issues: list[AuditIssue] = []
    is_summary = bool(re.search(r"摘要|结论总览", title))
    if not is_summary and not _QUESTION_CUES.search(f"{title}\n{visible}"):
        issues.append(AuditIssue("error", "section_question_not_clear", artifact, scope, 1, "章节没有让读者看出它正在回答什么问题；不要求固定小标题，但必须自然提出问题。"))
    if not _EVIDENCE_CUES.search(visible):
        issues.append(AuditIssue("error", "section_evidence_not_explained", artifact, scope, 1, "章节没有用自然语言说明哪些证据或数据约束了判断。"))
    if not _ANALYSIS_CUES.search(visible):
        issues.append(AuditIssue("error", "section_conclusion_not_clear", artifact, scope, 1, "章节没有把证据转成明确分析与结论。"))
    if _CALCULATION_TOPIC.search(f"{title}\n{visible}") and not _METHOD_CUES.search(visible):
        issues.append(AuditIssue("error", "section_method_not_explained", artifact, scope, 1, "章节涉及概率、市场或财务估算，但没有说明输入、假设或计算方法。"))
    if role == "entity" and re.search(r"(?:字段|完成状态|完成矩阵|覆盖卡|逐项完成|审计清单)", visible):
        issues.append(AuditIssue("error", "entity_field_matrix", artifact, scope, 1, "实体页退化为字段完成矩阵或审计清单，应改成证据关系与结论分析。"))
    return issues


def _paragraphs(text: str) -> list[tuple[str, int, str]]:
    paragraphs: list[tuple[str, int, str]] = []
    for match in re.finditer(r"(?ms)(?:^|\n\s*\n)([^\n].*?)(?=\n\s*\n|\Z)", text):
        raw = match.group(1).strip()
        if not raw or raw.startswith("|") or re.fullmatch(r"#{1,6}\s+.*", raw):
            continue
        visible = _visible_text(raw)
        visible = re.sub(r"(?m)^#{1,6}\s+", "", visible)
        visible = re.sub(r"[`*_~<>]", "", visible)
        normalized = re.sub(r"\s+", " ", visible).strip().casefold()
        if len(normalized) >= _LONG_PARAGRAPH_MIN_CHARS:
            paragraphs.append((normalized, _line_number(text, match.start(1)), raw))
    return paragraphs


def _duplicate_paragraph_issues(
    texts: Iterable[tuple[str, str, str]],
    *,
    artifact: str,
) -> list[AuditIssue]:
    """Find exact repeated long prose within and across public surfaces."""

    issues: list[AuditIssue] = []
    seen: dict[str, tuple[str, int]] = {}
    for scope, title, text in texts:
        for normalized, line, raw in _paragraphs(text):
            previous = seen.get(normalized)
            if previous is None:
                seen[normalized] = (scope, line)
                continue
            issues.append(
                AuditIssue(
                    "error",
                    "long_paragraph_duplicate",
                    artifact,
                    scope,
                    line,
                    f"长段落与 {previous[0]} 第 {previous[1]} 行重复；应删除模板复写或补充该章节独有分析。",
                    re.sub(r"\s+", " ", raw)[:140],
                )
            )
    return issues


def audit_markdown_scope(
    text: str,
    *,
    artifact: str,
    scope: str,
    title: str,
    role: str,
    enforce_structure: bool = True,
    target_profile: bool = False,
) -> ScopeAudit:
    visible = _visible_text(text)
    formula_visible = re.sub(
        r"(?<!\\)\*\*(.+?)(?<!\\)\*\*",
        r"\1",
        visible,
        flags=re.DOTALL,
    )
    issues: list[AuditIssue] = []
    for code, pattern, message in _effective_term_rules(target_profile):
        _aggregate_pattern_issue(issues, pattern=pattern, code=code, message=message, text=visible, artifact=artifact, scope=scope)
    for code, pattern, message in _RAW_FORMULA_PATTERNS:
        _aggregate_pattern_issue(
            issues,
            pattern=pattern,
            code=code,
            message=message,
            text=formula_visible,
            artifact=artifact,
            scope=scope,
        )
    text_outside_math = re.sub(r"\${1,2}[^$]*?\${1,2}", "", visible)
    _aggregate_pattern_issue(
        issues,
        pattern=_RAW_TEX_COMMAND_RE,
        code="formula_raw_tex_command",
        message="正文出现未被数学渲染边界包裹的 TeX 命令。",
        text=text_outside_math,
        artifact=artifact,
        scope=scope,
    )
    _aggregate_pattern_issue(issues, pattern=_BARE_URL_RE, code="bare_url", message="公开正文出现裸 URL；应使用有标题的来源按钮或 Markdown 链接。", text=visible, artifact=artifact, scope=scope)
    _aggregate_pattern_issue(issues, pattern=_WINDOWS_PATH_RE, code="disk_path", message="公开正文暴露 Windows 磁盘路径。", text=visible, artifact=artifact, scope=scope)
    _aggregate_pattern_issue(issues, pattern=_PROJECT_PATH_RE, code="project_path", message="公开正文暴露项目内部路径。", text=visible, artifact=artifact, scope=scope)
    _aggregate_pattern_issue(issues, pattern=_JSON_FENCE_RE, code="raw_json", message="公开正文包含原始 JSON 代码块。", text=visible, artifact=artifact, scope=scope)
    _aggregate_pattern_issue(issues, pattern=_JSON_LINE_RE, code="raw_json", message="公开正文包含疑似原始 JSON 对象。", text=visible, artifact=artifact, scope=scope)
    tables = parse_markdown_tables(text, artifact=artifact, scope=scope, default_heading=title)
    issues.extend(_audit_tables(tables))
    for table in tables:
        for column_index, header in enumerate(table.headers):
            if re.fullmatch(r"(?:未知|状态|完成情况|本轮代理|受影响参数|参数\s*owner|对账|最低可证含义|不可推出|架构状态)", _normalized_cell(header), re.IGNORECASE):
                issues.append(AuditIssue("error", "table_machine_column", artifact, scope, table.start_line, f"第 {column_index + 1} 列“{header}”是机器状态或低信息字段。", " | ".join(table.headers)))
    if enforce_structure:
        issues.extend(_structure_issues(text, artifact=artifact, scope=scope, title=title, role=role))
    return ScopeAudit(issues=issues, tables=tables)


def _table_category(table: MarkdownTable) -> set[str]:
    context = table.context
    categories: set[str] = set()
    if re.search(r"(?:概率|进入可能性|至少一家|两家均进入|有意义进入|\bprobability\b)", context, re.IGNORECASE):
        categories.add("probability")
    finance_terms = re.findall(r"(?:财务|收入|净利润|利润|自由现金流|毛利率|估值|终值|市盈率|市净率|现金流)", context)
    if len(set(finance_terms)) >= 2 or re.search(r"(?:财务|盈利|估值|终值|敏感性)", table.scope):
        categories.add("finance")
    return categories


def _finance_roles(table: MarkdownTable) -> set[str]:
    context = table.context
    roles: set[str] = set()
    if re.search(r"(?:历史|实际值|2023|2024|2025)", context):
        roles.add("historical")
    if re.search(r"(?:未来|预测|情景|202[6-9]|203[01])", context):
        roles.add("future")
    if re.search(r"(?:敏感性|暴露比例|风险暴露|假设变化|不同假设)", context):
        roles.add("sensitivity")
    return roles


def _portfolio_issues(
    tables: list[MarkdownTable],
    *,
    artifact: str,
    require_finance_roles: bool,
    public_text: str = "",
) -> list[AuditIssue]:
    probability = [table for table in tables if "probability" in _table_category(table)]
    finance = [table for table in tables if "finance" in _table_category(table)]
    issues: list[AuditIssue] = []
    if len(probability) > 2:
        issues.append(AuditIssue("error", "probability_table_limit", artifact, "main_report", probability[2].start_line, f"概率专题共有 {len(probability)} 张表，公开报告最多保留 2 张。"))
    if len(finance) > 3:
        issues.append(AuditIssue("error", "finance_table_limit", artifact, "main_report", finance[3].start_line, f"财务专题共有 {len(finance)} 张表，公开报告最多保留 3 张。"))
    if require_finance_roles:
        found: set[str] = set()
        for table in finance:
            found.update(_finance_roles(table))
        labels = {"historical": "核心历史财务表", "future": "未来情景结果表"}
        for role, label in labels.items():
            if role not in found:
                issues.append(AuditIssue("error", f"finance_{role}_table_missing", artifact, "main_report", None, f"无法识别{label}；表名与列名必须让读者直接看懂其用途。"))
        # 敏感性不强制做成表。若变量与结果可以用一句话说明，重复铺三档
        # 数字反而降低信息密度；但正文必须明确写出输入变化和量化结果。
        sensitivity_prose = re.search(
            r"(?:敏感度|敏感性).{0,180}(?:每增加|每减少|提高|下降).{0,80}"
            r"(?:个百分点|%|亿元).{0,320}(?:收入|净利润|利润|现金流|估值)",
            _visible_text(public_text),
            re.DOTALL,
        )
        if "sensitivity" not in found and sensitivity_prose is None:
            issues.append(
                AuditIssue(
                    "error",
                    "finance_sensitivity_analysis_missing",
                    artifact,
                    "main_report",
                    None,
                    "缺少能够改变结论的量化敏感性分析；可以用一张表，也可以直接写清输入变化与财务结果，不要求为表格而表格。",
                )
            )
    return issues


def _is_target_profile(pack: dict[str, Any], profile: str) -> bool:
    if profile == "byd_luxshare":
        return True
    if profile == "generic":
        return False
    identity = " ".join(str(pack.get(key, "")) for key in ("slug", "display_title", "research_question"))
    return bool(re.search(r"(?:比亚迪|BYD).*(?:立讯|Luxshare)|(?:立讯|Luxshare).*(?:比亚迪|BYD)", identity, re.IGNORECASE | re.DOTALL))


def _audit_public_value(
    value: Any,
    *,
    artifact: str,
    scope: str,
    target_profile: bool,
) -> list[AuditIssue]:
    if value is None or isinstance(value, (dict, list, tuple)):
        return []
    text = str(value).strip()
    if not text:
        return []
    return audit_markdown_scope(
        text,
        artifact=artifact,
        scope=scope,
        title=scope,
        role="metadata",
        enforce_structure=False,
        target_profile=target_profile,
    ).issues


def _audit_user_authored_question(value: Any, *, artifact: str, scope: str) -> list[AuditIssue]:
    """Apply only safety checks to the immutable original user request.

    The canonical research_question must preserve the user's wording for auditability.
    Producer style rules therefore apply to problem_statement and authored sections,
    while the original request is still blocked from leaking URLs, disk paths, internal
    URIs or raw JSON into the public page.
    """

    text = str(value or "").strip()
    if not text:
        return []
    visible = _visible_text(text)
    issues: list[AuditIssue] = []
    for code, pattern, message in _USER_QUESTION_SAFETY_RULES:
        _aggregate_pattern_issue(
            issues,
            pattern=pattern,
            code=code,
            message=message,
            text=visible,
            artifact=artifact,
            scope=scope,
        )
    return issues


def _iter_visual_public_values(value: Any, *, path: str = "data") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if _VISUAL_HIDDEN_KEY_RE.search(key_text):
                continue
            if isinstance(item, (dict, list, tuple)):
                yield from _iter_visual_public_values(item, path=child_path)
            elif isinstance(item, str) and _VISUAL_VISIBLE_KEY_RE.search(key_text):
                yield child_path, item
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _iter_visual_public_values(item, path=f"{path}[{index}]")


def _public_surface_issues(
    pack: dict[str, Any],
    *,
    artifact: str,
    target_profile: bool,
) -> tuple[list[AuditIssue], list[tuple[str, str, str]]]:
    issues: list[AuditIssue] = []
    prose: list[tuple[str, str, str]] = []

    def add(scope: str, value: Any, *, track_duplicate: bool = True) -> None:
        if value is None or isinstance(value, (dict, list, tuple)):
            return
        text = str(value).strip()
        if not text:
            return
        issues.extend(
            _audit_public_value(
                text,
                artifact=artifact,
                scope=scope,
                target_profile=target_profile,
            )
        )
        if track_duplicate:
            prose.append((scope, scope, text))

    for field in _PUBLIC_TOP_LEVEL_FIELDS:
        if field == "research_question" and str(pack.get("problem_statement") or "").strip():
            issues.extend(
                _audit_user_authored_question(
                    pack.get(field),
                    artifact=artifact,
                    scope="pack.research_question",
                )
            )
            continue
        add(f"pack.{field}", pack.get(field))

    for index, source in enumerate(pack.get("sources") or []):
        if not isinstance(source, dict):
            continue
        source_key = str(source.get("ref") or index)
        for field in _PUBLIC_SOURCE_FIELDS:
            add(f"sources[{source_key}].{field}", source.get(field))

    section_entity_keys = {
        str(section.get("entity_key"))
        for section in pack.get("entity_sections") or []
        if isinstance(section, dict) and section.get("entity_key")
    }
    for index, entity in enumerate(pack.get("entities") or []):
        if not isinstance(entity, dict):
            continue
        entity_key = str(entity.get("key") or index)
        for field in _PUBLIC_ENTITY_FIELDS:
            add(f"entities[{entity_key}].{field}", entity.get(field))
        # research_profile is a public fallback only when no authored entity section
        # exists. When an entity section exists, the profile remains internal audit data.
        if entity_key not in section_entity_keys:
            profile_payload = entity.get("research_profile")
            if isinstance(profile_payload, dict):
                for field in _PUBLIC_PROFILE_FIELDS:
                    add(f"entities[{entity_key}].research_profile.{field}", profile_payload.get(field))

    for index, target in enumerate(pack.get("entity_investment_targets") or []):
        if not isinstance(target, dict):
            continue
        target_key = str(target.get("target_name") or target.get("ticker") or index)
        for field in _PUBLIC_TARGET_FIELDS:
            add(f"targets[{target_key}].{field}", target.get(field))
        for point_index, point in enumerate(target.get("target_data_points") or []):
            if not isinstance(point, dict):
                continue
            for field in _PUBLIC_TARGET_POINT_FIELDS:
                add(
                    f"targets[{target_key}].points[{point_index}].{field}",
                    point.get(field),
                    # 中文来源常按合同同时存原文和中文译意；两字段相同不是
                    # 公开分析段落复写，仍执行词表扫描但不进入重复 prose gate。
                    track_duplicate=field not in {"source_excerpt", "source_excerpt_zh"},
                )

    for index, visual in enumerate(pack.get("visuals") or []):
        if not isinstance(visual, dict):
            continue
        visual_key = str(visual.get("block_key") or index)
        for field in _PUBLIC_VISUAL_FIELDS:
            add(f"visuals[{visual_key}].{field}", visual.get(field))
        for container in ("data", "display_data", "print_fallback"):
            for path, text in _iter_visual_public_values(visual.get(container), path=container):
                add(f"visuals[{visual_key}].{path}", text)

    for index, item in enumerate(pack.get("nav") or []):
        if not isinstance(item, dict):
            continue
        for field in _PUBLIC_NAV_FIELDS:
            add(f"nav[{index}].{field}", item.get(field))

    for index, item in enumerate(pack.get("supplement_requests") or []):
        if not isinstance(item, dict):
            continue
        for field in _PUBLIC_SUPPLEMENT_FIELDS:
            add(f"supplement_requests[{index}].{field}", item.get(field))

    return issues, prose


def audit_run_pack(pack: dict[str, Any], *, artifact: str, profile: str = "auto") -> tuple[list[AuditIssue], dict[str, int]]:
    issues: list[AuditIssue] = []
    main_tables: list[MarkdownTable] = []
    section_count = 0
    entity_count = 0
    target_profile = _is_target_profile(pack, profile)
    display_title = str(pack.get("display_title") or "").strip()
    if not display_title:
        issues.append(
            AuditIssue(
                "error",
                "display_title_missing",
                artifact,
                "pack.display_title",
                None,
                "公开研究包缺少简短展示标题；完整研究问题不能直接代替列表和页头标题。",
            )
        )
    elif len(display_title) > 24:
        issues.append(
            AuditIssue(
                "warning",
                "display_title_too_long",
                artifact,
                "pack.display_title",
                None,
                "展示标题超过建议的 24 个字符；应在不丢失主体和研究对象的前提下进一步概括。",
                display_title,
            )
        )
    public_surface_issues, public_prose = _public_surface_issues(
        pack,
        artifact=artifact,
        target_profile=target_profile,
    )
    issues.extend(public_surface_issues)
    section_keys: set[str] = set()
    section_titles: set[str] = set()
    main_public_texts: list[str] = []
    for index, section in enumerate(pack.get("sections") or []):
        if not isinstance(section, dict):
            issues.append(AuditIssue("error", "section_not_object", artifact, f"sections[{index}]", None, "公开章节不是对象。"))
            continue
        section_count += 1
        key = str(section.get("section_key") or f"section_{index + 1}")
        title = str(section.get("section_title") or key)
        body = str(section.get("body_markdown") or "")
        if key in section_keys:
            issues.append(AuditIssue("error", "section_key_duplicate", artifact, f"section:{key}", None, "公开章节 key 重复，最终报告无法稳定对齐章节。"))
        section_keys.add(key)
        normalized_title = re.sub(r"\s+", " ", title).strip().casefold()
        if normalized_title in section_titles:
            issues.append(AuditIssue("error", "section_title_duplicate", artifact, f"section:{key}", None, "公开章节标题重复，应合并重叠章节或改成能够区分问题的标题。", title))
        section_titles.add(normalized_title)
        if not body.strip():
            issues.append(AuditIssue("error", "section_body_missing", artifact, f"section:{key}", None, "公开章节正文为空。"))
        title_issues = _audit_public_value(title, artifact=artifact, scope=f"section:{key}.title", target_profile=target_profile)
        issues.extend(title_issues)
        result = audit_markdown_scope(body, artifact=artifact, scope=f"section:{key}", title=title, role="section", target_profile=target_profile)
        issues.extend(result.issues)
        main_tables.extend(result.tables)
        main_public_texts.append(body)
        public_prose.append((f"section:{key}", title, body))
    entity_keys: set[str] = set()
    entity_titles: set[str] = set()
    for index, section in enumerate(pack.get("entity_sections") or []):
        if not isinstance(section, dict):
            issues.append(AuditIssue("error", "entity_section_not_object", artifact, f"entity_sections[{index}]", None, "实体公开章节不是对象。"))
            continue
        entity_count += 1
        key = str(section.get("entity_key") or section.get("section_key") or f"entity_{index + 1}")
        title = str(section.get("section_title") or key)
        body = str(section.get("body_markdown") or "")
        if key in entity_keys:
            issues.append(AuditIssue("error", "entity_section_key_duplicate", artifact, f"entity:{key}", None, "同一实体存在重复公开章节 key。"))
        entity_keys.add(key)
        normalized_title = re.sub(r"\s+", " ", title).strip().casefold()
        if normalized_title in entity_titles:
            issues.append(AuditIssue("error", "entity_section_title_duplicate", artifact, f"entity:{key}", None, "实体公开章节标题重复。", title))
        entity_titles.add(normalized_title)
        if not body.strip():
            issues.append(AuditIssue("error", "entity_section_body_missing", artifact, f"entity:{key}", None, "实体公开章节正文为空。"))
        issues.extend(_audit_public_value(title, artifact=artifact, scope=f"entity:{key}.title", target_profile=target_profile))
        result = audit_markdown_scope(body, artifact=artifact, scope=f"entity:{key}", title=title, role="entity", target_profile=target_profile)
        issues.extend(result.issues)
        if len(result.tables) > 3:
            issues.append(AuditIssue("error", "entity_table_overload", artifact, f"entity:{key}", result.tables[3].start_line, f"实体页有 {len(result.tables)} 张表，已经退化为表格堆叠；应保留少量不可替代的横向比较。"))
        public_prose.append((f"entity:{key}", title, body))
    issues.extend(_duplicate_paragraph_issues(public_prose, artifact=artifact))
    if target_profile:
        issues.extend(
            _portfolio_issues(
                main_tables,
                artifact=artifact,
                require_finance_roles=True,
                public_text="\n\n".join(main_public_texts),
            )
        )
    issues.extend(_cross_table_duplicate_issues(main_tables, artifact=artifact))
    return issues, {
        "sections": section_count,
        "entity_sections": entity_count,
        "main_tables": len(main_tables),
        "public_surface_values": len(public_prose),
    }


def _markdown_sections(text: str) -> list[tuple[str, str, int]]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if not matches:
        return [("完整报告", text, 1)]
    sections: list[tuple[str, str, int]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(1).strip(), text[match.end():end], _line_number(text, match.start())))
    return sections


def audit_report_markdown(
    text: str,
    *,
    artifact: str,
    enforce_portfolio: bool,
    require_finance_roles: bool,
    target_profile: bool = False,
) -> tuple[list[AuditIssue], dict[str, int]]:
    # 全文扫描能发现来源附录、实体附录或拼接边界泄露的机器术语；章节结构在
    # run pack 已逐节检查时不重复，以免把来源索引误判成研究章节。
    overall = audit_markdown_scope(
        text,
        artifact=artifact,
        scope="final_report",
        title="完整报告",
        role="report",
        enforce_structure=False,
        target_profile=target_profile,
    )
    issues = list(overall.issues)
    issues.extend(
        _duplicate_paragraph_issues(
            [("final_report", "完整报告", text)],
            artifact=artifact,
        )
    )
    if enforce_portfolio and target_profile:
        issues.extend(
            _portfolio_issues(
                overall.tables,
                artifact=artifact,
                require_finance_roles=require_finance_roles,
                public_text=text,
            )
        )
    return issues, {"markdown_sections": len(_markdown_sections(text)), "tables": len(overall.tables)}


def _normalize_heading(value: str) -> str:
    value = re.sub(r"^[#\s]+", "", value)
    value = re.sub(r"^\d+(?:\.\d+)*[、.．)）\s]+", "", value)
    value = re.sub(r"[`*_~]", "", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_report_text(value: str) -> str:
    value = _visible_text(value)
    value = re.sub(r"(?m)^#{1,6}\s+", "", value)
    value = re.sub(r"[`*_~]", "", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def _report_consistency_issues(
    pack: dict[str, Any],
    report_text: str,
    *,
    artifact: str,
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    if not report_text.strip():
        return [AuditIssue("error", "final_report_empty", artifact, "final_report", 1, "final_report.md 为空。")]
    heading_matches = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", report_text))
    headings = [_normalize_heading(match.group(2)) for match in heading_matches]
    h1 = next((match for match in heading_matches if len(match.group(1)) == 1), None)
    display_title = str(pack.get("display_title") or "").strip()
    if display_title:
        if h1 is None:
            issues.append(AuditIssue("error", "final_report_title_missing", artifact, "final_report", 1, "最终报告缺少一级标题。"))
        elif _normalize_heading(h1.group(2)) != _normalize_heading(display_title):
            issues.append(
                AuditIssue(
                    "error",
                    "final_report_title_mismatch",
                    artifact,
                    "final_report",
                    _line_number(report_text, h1.start()),
                    "最终报告一级标题与 run pack 的公开标题不一致。",
                    h1.group(2).strip(),
                )
            )
    normalized_report = _normalize_report_text(report_text)
    # final_report.md 是主报告；实体研究由独立实体页面完整展示。把实体全文再次
    # 拼进主报告会造成大段重复，公开质量审计只要求十个主章节完整保留。
    for collection, prefix in ((pack.get("sections") or [], "section"),):
        for index, section in enumerate(collection):
            if not isinstance(section, dict):
                continue
            key = str(section.get("section_key") or section.get("entity_key") or index)
            title = str(section.get("section_title") or "").strip()
            body = str(section.get("body_markdown") or "")
            body_heading = re.search(r"(?m)^#{1,6}\s+(.+?)\s*$", body)
            candidate_titles = [title]
            if prefix == "entity" and body_heading is not None:
                candidate_titles.append(body_heading.group(1).strip())
            normalized_candidates = {
                _normalize_heading(candidate)
                for candidate in candidate_titles
                if candidate.strip()
            }
            candidate_counts = {
                candidate: sum(heading == candidate for heading in headings)
                for candidate in normalized_candidates
            }
            matches = max(candidate_counts.values(), default=0)
            if not any(candidate_counts.values()):
                expected = " / ".join(candidate_titles) or key
                issues.append(AuditIssue("error", "final_report_section_missing", artifact, f"{prefix}:{key}", None, f"最终报告缺少章节“{expected}”。"))
            elif matches > 1:
                issues.append(AuditIssue("error", "final_report_section_duplicate", artifact, f"{prefix}:{key}", None, f"最终报告重复出现章节“{title or key}”。", count=matches))
            body_paragraphs = [item for item in _paragraphs(body)]
            # Full authored sections can change heading levels in the assembled report,
            # but their substantive long paragraphs must survive the assembly.
            missing_paragraphs = [raw for normalized, _, raw in body_paragraphs if normalized not in normalized_report]
            if missing_paragraphs:
                issues.append(
                    AuditIssue(
                        "error",
                        "final_report_section_incomplete",
                        artifact,
                        f"{prefix}:{key}",
                        None,
                        f"最终报告遗漏了“{title or key}”中的 {len(missing_paragraphs)} 个长段落。",
                        re.sub(r"\s+", " ", missing_paragraphs[0])[:140],
                        count=len(missing_paragraphs),
                    )
                )
    return issues


def _sort_issues(issues: Iterable[AuditIssue]) -> list[AuditIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            0 if issue.severity == "error" else 1,
            issue.artifact,
            issue.scope,
            issue.line if issue.line is not None else 10**9,
            issue.code,
        ),
    )


def _result_payload(
    *,
    issues: Iterable[AuditIssue],
    metrics: dict[str, int],
    artifacts: list[dict[str, Any]],
    target_profile: bool,
) -> dict[str, Any]:
    ordered = _sort_issues(issues)
    errors = sum(issue.severity == "error" for issue in ordered)
    warnings = sum(issue.severity == "warning" for issue in ordered)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if errors == 0 else "FAIL",
        "profile": "byd_luxshare" if target_profile else "generic",
        "rules_sha256": _rules_hash(target_profile=target_profile),
        "summary": {"errors": errors, "warnings": warnings, "issues": len(ordered)},
        "metrics": metrics,
        "artifacts": artifacts,
        "issues": [asdict(issue) for issue in ordered],
    }


def audit_pack_document(
    pack: dict[str, Any],
    *,
    profile: str = "auto",
    artifact: str = "run_pack",
) -> dict[str, Any]:
    target_profile = _is_target_profile(pack, profile)
    pack_issues, pack_metrics = audit_run_pack(pack, artifact=artifact, profile=profile)
    return _result_payload(
        issues=pack_issues,
        metrics={f"run_pack_{key}": value for key, value in pack_metrics.items()},
        artifacts=[
            {
                "kind": "run_pack",
                "path": artifact,
                "sha256": public_pack_hash(pack),
            }
        ],
        target_profile=target_profile,
    )


def build_pack_audit_attestation(pack: dict[str, Any], *, profile: str = "auto") -> dict[str, Any]:
    result = audit_pack_document(pack, profile=profile, artifact="run_pack")
    return {
        "schema_version": result["schema_version"],
        "status": result["status"],
        "profile": result["profile"],
        "rules_sha256": result["rules_sha256"],
        "pack_sha256": public_pack_hash(pack),
        "hash_scope": "canonical_json_without_embedded_audit_or_runtime_fields; not the raw run_pack file hash",
        "result_sha256": _hash_json(result),
        "summary": result["summary"],
    }


def validate_pack_audit_attestation(
    pack: dict[str, Any],
    *,
    profile: str = "auto",
) -> tuple[dict[str, Any], list[str]]:
    """Re-audit authored public content and validate any embedded attestation.

    Missing attestations are accepted for V2 migration and rebuilt in memory. Once an
    attestation is present, any content/rules/result change makes it stale and blocks
    validation until the producer reruns the audit.
    """

    supplied = pack.get(PUBLIC_AUDIT_FIELD)
    computed = build_pack_audit_attestation(pack, profile=profile)
    errors: list[str] = []
    if computed["status"] != "PASS":
        result = audit_pack_document(pack, profile=profile, artifact="run_pack")
        codes = [str(issue.get("code")) for issue in result.get("issues", [])[:8]]
        errors.append(
            "公开内容质量审计失败："
            f"errors={computed['summary']['errors']}，rules={','.join(codes) or '未分类'}"
        )
    if supplied is not None:
        if not isinstance(supplied, dict):
            errors.append("公开内容审计记录不是对象")
        else:
            required = (
                "schema_version",
                "status",
                "profile",
                "rules_sha256",
                "pack_sha256",
                "result_sha256",
            )
            missing = [key for key in required if key not in supplied]
            if missing:
                errors.append("公开内容审计记录缺少字段：" + ", ".join(missing))
            changed = [key for key in required if key in supplied and supplied.get(key) != computed.get(key)]
            if changed:
                errors.append(
                    "公开内容审计记录已失效，pack 内容、规则或结果发生变化："
                    + ", ".join(changed)
                )
    return computed, errors


def run_audit(
    *,
    run_pack_path: Path | None,
    report_path: Path | None,
    profile: str = "auto",
) -> dict[str, Any]:
    issues: list[AuditIssue] = []
    artifacts: list[dict[str, Any]] = []
    metrics: dict[str, int] = {}
    target_profile = profile == "byd_luxshare"
    pack: dict[str, Any] | None = None
    if run_pack_path is not None:
        pack = json.loads(run_pack_path.read_text(encoding="utf-8"))
        pack_issues, pack_metrics = audit_run_pack(pack, artifact=str(run_pack_path), profile=profile)
        issues.extend(pack_issues)
        metrics.update({f"run_pack_{key}": value for key, value in pack_metrics.items()})
        target_profile = _is_target_profile(pack, profile)
        artifacts.append({"kind": "run_pack", "path": str(run_pack_path), "sha256": _HASH_PREFIX + _sha256(run_pack_path)})
    if report_path is not None:
        report_text = report_path.read_text(encoding="utf-8")
        report_issues, report_metrics = audit_report_markdown(
            report_text,
            artifact=str(report_path),
            enforce_portfolio=run_pack_path is None,
            require_finance_roles=target_profile,
            target_profile=target_profile,
        )
        issues.extend(report_issues)
        if pack is not None:
            issues.extend(_report_consistency_issues(pack, report_text, artifact=str(report_path)))
        metrics.update({f"report_{key}": value for key, value in report_metrics.items()})
        artifacts.append({"kind": "final_report", "path": str(report_path), "sha256": _HASH_PREFIX + _sha256(report_path)})
    return _result_payload(
        issues=issues,
        metrics=metrics,
        artifacts=artifacts,
        target_profile=target_profile,
    )


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Opportunity Lens 公开内容质量审计",
        "",
        f"- 结果：**{result['status']}**",
        f"- 错误：{summary['errors']}",
        f"- 警告：{summary['warnings']}",
        f"- 审计配置：{result['profile']}",
        "",
        "## 输入产物",
        "",
    ]
    for artifact in result["artifacts"]:
        lines.append(f"- `{artifact['kind']}`：`{artifact['path']}`（SHA256 `{artifact['sha256']}`）")
    lines.extend(["", "## 发现", ""])
    if not result["issues"]:
        lines.append("未发现阻断性公开内容问题。")
    else:
        lines.append("| 严重性 | 规则 | 位置 | 发现 | 次数 |")
        lines.append("|---|---|---|---|---:|")
        for issue in result["issues"]:
            location = f"{issue['scope']}"
            if issue["line"] is not None:
                location += f":{issue['line']}"
            message = str(issue["message"]).replace("|", "\\|")
            excerpt = str(issue.get("excerpt") or "").replace("|", "\\|")
            if excerpt:
                message += f"；首处：{excerpt}"
            lines.append(f"| {issue['severity']} | `{issue['code']}` | {location} | {message} | {issue['count']} |")
    lines.extend(["", "## 判定规则", "", "只要存在 `error` 即为 FAIL；必须修订生成器并重新生成产物后复跑，不能在审计输出中豁免。", ""])
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="审计 Opportunity Lens 公开报告的人类可读性、表格信息价值和机器字段泄露。")
    parser.add_argument("--run-pack", type=Path, help="生成后的 run_pack.json")
    parser.add_argument("--report", type=Path, help="生成后的 final_report.md；省略时会尝试读取 run pack 同目录文件")
    parser.add_argument("--profile", choices=("auto", "generic", "byd_luxshare"), default="auto")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_pack_path: Path | None = args.run_pack
    report_path: Path | None = args.report
    if run_pack_path is None and report_path is None:
        raise SystemExit("必须提供 --run-pack 或 --report")
    if run_pack_path is not None and not run_pack_path.is_file():
        raise SystemExit(f"run pack 不存在：{run_pack_path}")
    if report_path is None and run_pack_path is not None:
        candidate = run_pack_path.with_name("final_report.md")
        if candidate.is_file():
            report_path = candidate
    if report_path is not None and not report_path.is_file():
        raise SystemExit(f"报告不存在：{report_path}")
    result = run_audit(run_pack_path=run_pack_path, report_path=report_path, profile=args.profile)
    json_text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    markdown_text = render_markdown(result)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json_text, encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_text, encoding="utf-8")
    if not args.json_output and not args.markdown_output:
        print(markdown_text)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
