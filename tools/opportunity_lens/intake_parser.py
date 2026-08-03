from __future__ import annotations

import re
from typing import Any

from .intake_contract import (
    canonical_contract_payload,
    material_type_from_choice,
    normalize_available_materials_choice,
    normalize_evidence_policy,
)
from .validators import validate_no_forbidden_public_fields


def parse_intake_payload(payload: dict[str, Any], *, allow_legacy_alias: bool = False) -> dict[str, Any]:
    """把用户入口 payload 归一化为当前 intake contract 字段。

    公开 API 必须传 `research_question` 和 `available_materials_choice`。
    `available_materials_state` 只给历史表单导入使用，归一化后不会继续向下游传播。
    """
    data = dict(payload or {})
    if not allow_legacy_alias:
        validate_no_forbidden_public_fields(data)
        if "available_materials_choice" not in data:
            raise ValueError("公开 intake payload 必须显式提供 available_materials_choice")
    if allow_legacy_alias and "available_materials_choice" not in data and "available_materials_state" in data:
        data["available_materials_choice"] = data.pop("available_materials_state")
        origin = dict(data.get("field_origin") or {})
        origin["available_materials_choice"] = "raw_alias_normalized"
        data["field_origin"] = origin
    if allow_legacy_alias and "research_question" not in data and "question" in data:
        data["research_question"] = data.pop("question")
        origin = dict(data.get("field_origin") or {})
        origin["research_question"] = "raw_alias_normalized"
        data["field_origin"] = origin
    choice = normalize_available_materials_choice(data.get("available_materials_choice"))
    data["available_materials_choice"] = choice
    data["intake_material_type"] = data.get("intake_material_type") or material_type_from_choice(choice)
    data["evidence_policy"] = normalize_evidence_policy(data.get("evidence_policy"))
    return canonical_contract_payload(data)


def parse_markdown_intake_text(text: str) -> dict[str, Any]:
    """Parse both the fenced formal template and the legacy key-value format."""
    body = text or ""

    def sections() -> list[tuple[str, str]]:
        # Research questions are fenced verbatim and may legitimately contain
        # Markdown headings of their own (for example ``## 晶体生长``).  Those
        # headings belong to the question, not to the surrounding intake form.
        # Only recognise level-two headings while outside fenced code blocks.
        headings: list[tuple[int, int, str]] = []
        in_fence = False
        offset = 0
        for line in body.splitlines(keepends=True):
            stripped = line.lstrip()
            if stripped.startswith("```"):
                in_fence = not in_fence
            elif not in_fence:
                match = re.match(r"^##\s+(.+?)\s*(?:\r?\n)?$", line)
                if match:
                    headings.append((offset, offset + len(line), match.group(1).strip()))
            offset += len(line)
        result: list[tuple[str, str]] = []
        for index, (_start, heading_end, title) in enumerate(headings):
            section_end = headings[index + 1][0] if index + 1 < len(headings) else len(body)
            result.append((title, body[heading_end:section_end]))
        return result

    parsed_sections = sections()

    def find_section(keyword: str) -> str:
        for title, content in parsed_sections:
            if keyword in title:
                return content
        return ""

    def first_code_block(content: str) -> str:
        match = re.search(r"```(?:text|markdown|md|json)?\s*\n(.*?)\n```", content, flags=re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def labeled_code_block(content: str, label_pattern: str) -> str:
        match = re.search(
            rf"(?:{label_pattern})\s*[:：]?\s*\n+```(?:text|markdown|md|json)?\s*\n(.*?)\n```",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        return match.group(1).strip() if match else ""

    fields: dict[str, Any] = {}
    question_section = find_section("研究问题")
    materials_section = find_section("可用资料状态")
    policy_section = find_section("证据策略")
    time_section = find_section("时间窗口")
    scope_section = find_section("研究范围")
    constraints_section = find_section("特殊约束")

    if question_section:
        fields["research_question"] = first_code_block(question_section)
    if materials_section:
        choice = labeled_code_block(materials_section, r"选择（?A\s*/\s*B\s*/\s*C）?")
        fields["available_materials_choice"] = (choice[:1] or "A").upper()
        material_value = labeled_code_block(
            materials_section,
            r"资料路径\s*/\s*行研库行业名称(?:\s*/\s*资料包说明)?",
        )
        supplement = labeled_code_block(materials_section, r"补充说明")
        if fields["available_materials_choice"] == "B":
            looks_like_path = bool(re.search(r"(?:^[A-Za-z]:\\|^/|^\\\\|\bpapers[/\\])", material_value))
            if looks_like_path:
                fields["papers_or_report_folder"] = material_value
                if supplement:
                    fields["materials_delivery_note"] = supplement
            else:
                fields["materials_delivery_note"] = "\n\n".join(x for x in (material_value, supplement) if x)
        elif fields["available_materials_choice"] == "C":
            fields["reference_industry_in_research_db"] = material_value
        elif supplement:
            fields["materials_delivery_note"] = supplement
    if policy_section:
        raw_policy = labeled_code_block(policy_section, r"选择（?A\s*/\s*B\s*/\s*C）?")
        policy_map = {"A": "freshness_first", "B": "balanced", "C": "accuracy_first"}
        fields["evidence_policy"] = policy_map.get(raw_policy[:1].upper(), raw_policy or "balanced")

    if time_section:
        use_default = labeled_code_block(time_section, r"是否使用默认（?是\s*/\s*否）?") or "是"
        fields["time_window"] = {
            "use_default": use_default,
            "core_window": labeled_code_block(time_section, r"核心窗口"),
            "long_term_background": labeled_code_block(time_section, r"长期背景"),
        }
    if scope_section:
        use_default = labeled_code_block(scope_section, r"是否使用默认（?是\s*/\s*否）?") or "是"
        fields["research_scope"] = {
            "use_default": use_default,
            "geography": labeled_code_block(scope_section, r"地理范围"),
            "segments": labeled_code_block(scope_section, r"行业\s*/\s*环节"),
            "candidates": labeled_code_block(scope_section, r"公司\s*/\s*材料候选"),
            "must_include": labeled_code_block(scope_section, r"必须包含"),
            "must_exclude": labeled_code_block(scope_section, r"必须排除"),
        }
    if constraints_section:
        use_default = labeled_code_block(constraints_section, r"是否使用默认（?是\s*/\s*否）?") or "是"
        raw_constraints = labeled_code_block(constraints_section, r"特殊约束")
        fields["special_constraints"] = {"use_default": use_default, "text": raw_constraints}

    legacy_patterns = {
        "research_question": r"(?:research_question|研究问题|用户研究问题)\s*[:：]\s*(.+)",
        "available_materials_choice": r"(?:available_materials_choice|资料选择|材料选择)\s*[:：]\s*([ABCabc])",
        "evidence_policy": r"(?:evidence_policy|证据策略)\s*[:：]\s*(freshness_first|balanced|accuracy_first)",
        "papers_or_report_folder": r"(?:papers_or_report_folder|研报文件夹|资料文件夹)\s*[:：]\s*(.+)",
        "reference_industry_in_research_db": r"(?:reference_industry_in_research_db|参考行业)\s*[:：]\s*(.+)",
    }
    for key, pattern in legacy_patterns.items():
        if not fields.get(key):
            match = re.search(pattern, body)
            if match:
                fields[key] = match.group(1).strip()
    if not fields.get("research_question") and not question_section:
        first_heading = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
        if first_heading:
            fields["research_question"] = first_heading.group(1).strip()
    provided_keys = set(fields)
    fields.setdefault("available_materials_choice", "A")
    fields.setdefault("evidence_policy", "balanced")
    fields["field_origin"] = {
        key: "user_provided"
        for key, value in fields.items()
        if key in provided_keys and key != "field_origin" and value not in (None, "", {}, [])
    }
    for key in ("available_materials_choice", "evidence_policy"):
        if key not in provided_keys:
            fields["field_origin"][key] = "system_default"
    fields["default_accepted"] = {
        "available_materials_choice": "available_materials_choice" not in provided_keys,
        "evidence_policy": "evidence_policy" not in provided_keys,
        "time_window": (fields.get("time_window") or {}).get("use_default", "是") == "是",
        "research_scope": (fields.get("research_scope") or {}).get("use_default", "是") == "是",
        "special_constraints": (fields.get("special_constraints") or {}).get("use_default", "是") == "是",
    }
    return parse_intake_payload(fields, allow_legacy_alias=True)
