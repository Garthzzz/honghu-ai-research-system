from __future__ import annotations

import re
from urllib.parse import urlparse

from .state_registry import (
    AB_URI_TABLES,
    AUDIT_TRANSITIONS,
    ENUMS,
    GENERIC_REVIEW_TRANSITIONS,
    HISTORICAL_ALIASES,
    RUN_TRANSITIONS,
    STATUS_FIELD_TO_ENUM,
    TRANSITION_ENUM_BY_OBJECT_TYPE,
    URI_TABLES,
    is_valid,
)


class ValidationError(ValueError):
    pass


FORBIDDEN_PUBLIC_FIELDS = {"question", "user_question", "available_materials_state"}


def validate_no_forbidden_public_fields(payload, path: str = "$") -> None:
    """拒绝公开 API payload 中的历史别名字段。

    `available_materials_state` 只允许在 legacy intake parser 边界被读取并立即归一化，
    不能进入 DB、API 响应或后续业务逻辑。
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            current_path = f"{path}.{key}"
            if key in FORBIDDEN_PUBLIC_FIELDS:
                raise ValidationError(f"公开 payload 不得使用历史字段 {current_path}；请使用 research_question 与 available_materials_choice")
            validate_no_forbidden_public_fields(value, current_path)
    elif isinstance(payload, list):
        for idx, value in enumerate(payload):
            validate_no_forbidden_public_fields(value, f"{path}[{idx}]")


def validate_enum(enum_name: str, value: str | None) -> str:
    if value is None or enum_name not in ENUMS or value not in ENUMS[enum_name]:
        allowed = ", ".join(ENUMS.get(enum_name, ()))
        raise ValidationError(f"{value!r} 不是 {enum_name} 的合法取值；允许值：{allowed}")
    return value


def validate_status_field(field_name: str, value: str | None) -> str:
    if field_name in {"from_status", "to_status"}:
        raise ValidationError(f"{field_name} 必须结合 object_type 校验")
    enum_name = STATUS_FIELD_TO_ENUM.get(field_name)
    if not enum_name:
        raise ValidationError(f"{field_name} 不是已注册状态字段")
    return validate_enum(enum_name, value)


def validate_no_forbidden_alias(field_name: str, value: str | None) -> None:
    if value in HISTORICAL_ALIASES:
        raise ValidationError(
            f"{value!r} 是 {HISTORICAL_ALIASES[value]!r} 的历史说法；"
            f"不要写入 {field_name}"
        )


def _allowed_transition_set(object_type: str, from_status: str) -> set[str] | None:
    if object_type == "run":
        return RUN_TRANSITIONS.get(from_status)
    if object_type == "audit_issue":
        return AUDIT_TRANSITIONS.get(from_status)
    if object_type in {"supplement_request", "review_queue"}:
        return GENERIC_REVIEW_TRANSITIONS.get(from_status)
    return None


def validate_state_transition(object_type: str, from_status: str | None, to_status: str) -> str:
    enum_name = TRANSITION_ENUM_BY_OBJECT_TYPE.get(object_type)
    if not enum_name:
        raise ValidationError(f"未知状态迁移 object_type：{object_type}")
    if from_status is not None:
        validate_enum(enum_name, from_status)
        validate_no_forbidden_alias("from_status", from_status)
    validate_enum(enum_name, to_status)
    validate_no_forbidden_alias("to_status", to_status)
    if from_status is None:
        return to_status
    allowed = _allowed_transition_set(object_type, from_status)
    if allowed is not None and to_status not in allowed:
        raise ValidationError(f"{object_type} 状态迁移非法：{from_status} -> {to_status}")
    return to_status


def validate_uri(ref: str) -> tuple[str, str, int]:
    parsed = urlparse(ref or "")
    if parsed.scheme == "opp":
        object_type = parsed.netloc
        if object_type not in URI_TABLES:
            raise ValidationError(f"不支持的 opp URI 对象：{object_type}")
        ident = parsed.path.lstrip("/")
        if not re.fullmatch(r"\d+", ident or ""):
            raise ValidationError(f"opp URI id 非法：{ref}")
        return ("opp", object_type, int(ident))
    if parsed.scheme == "ab":
        object_type = parsed.netloc
        if object_type not in AB_URI_TABLES:
            raise ValidationError(f"不支持的 ab URI 对象：{object_type}")
        ident = parsed.path.lstrip("/")
        if not re.fullmatch(r"\d+", ident or ""):
            raise ValidationError(f"ab URI id 非法：{ref}")
        return ("ab", object_type, int(ident))
    raise ValidationError(f"不支持的证据 URI scheme：{ref}")


def normalize_entity_type(value: str) -> str:
    mapping = {
        "Company": "company",
        "company": "company",
        "product": "product_material",
        "ticker": "security",
        "listed_security": "security",
    }
    normalized = mapping.get(value, value)
    return validate_enum("entity_type", normalized)


def validate_score_contract(row: dict) -> None:
    for field in ("score_status", "score_grade", "rating_status", "score_quality_label"):
        if field in row:
            validate_status_field(field, row[field])
    if "entity_id" not in row:
        raise ValidationError("评分响应必须使用规范 entity_id")
    if "candidate_id" in row:
        raise ValidationError("公开评分响应不得使用 candidate_id")
    if row.get("score_status") == "complete" and not row.get("evidence_ref_uri_list"):
        raise ValidationError("完整评分必须有 evidence_ref_uri_list")


def assert_registered_status_payload(payload: dict) -> None:
    for key, value in payload.items():
        if key.endswith("_status") and key in STATUS_FIELD_TO_ENUM:
            validate_status_field(key, value)
        elif key.endswith("_status"):
            raise ValidationError(f"payload 中有未注册状态字段：{key}")


def is_registered_status_value(field_name: str, value: str) -> bool:
    enum_name = STATUS_FIELD_TO_ENUM.get(field_name)
    return bool(enum_name and is_valid(enum_name, value))
