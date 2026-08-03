from __future__ import annotations

import json
import sqlite3

from .validators import validate_enum


def build_policy_search_profile(evidence_policy: str) -> dict:
    """返回 evidence_policy 对检索计划的本地约束，不执行真实搜索。"""
    policy = validate_enum("evidence_policy", evidence_policy)
    base_axes = [
        {"axis_key": "demand", "label": "需求变化"},
        {"axis_key": "supply", "label": "供给约束"},
        {"axis_key": "price", "label": "价格和订单信号"},
        {"axis_key": "confirmation", "label": "独立确认"},
    ]
    profiles = {
        "freshness_first": {
            "source_groups": ["official_recent", "industry_media_recent", "company_ir", "ab_seed"],
            "stop_conditions": ["至少 1 个新鲜来源进入 early_signal_candidate", "核心评分仍需 A/B 级或独立确认"],
            "staleness_days": 30,
        },
        "balanced": {
            "source_groups": ["official", "industry_media", "research_report", "ab_seed"],
            "stop_conditions": ["普通因子至少 3 个证据组，重要因子至少 5 个证据组", "弱证据只进入补充或早期信号"],
            "staleness_days": 90,
        },
        "accuracy_first": {
            "source_groups": ["official", "filing", "research_report", "expert_verified", "ab_seed"],
            "stop_conditions": ["核心证据优先官方或多源确认", "未确认媒体信号不进入核心评分"],
            "staleness_days": 180,
        },
    }
    profile = dict(profiles[policy])
    profile.update({
        "evidence_policy": policy,
        "axes": base_axes,
        "real_search_executor": "deferred",
    })
    return profile


def create_search_plan(
    conn: sqlite3.Connection,
    run_id: int,
    plan_name: str,
    axes: list[dict],
    source_groups: list[str],
    search_protocol_version: str = "C_SEARCH_PROTOCOL_V1",
    evidence_policy: str | None = None,
) -> int:
    if evidence_policy:
        profile = build_policy_search_profile(evidence_policy)
        axes = axes or profile["axes"]
        source_groups = source_groups or profile["source_groups"]
    return int(
        conn.execute(
            """
            INSERT INTO opportunity_search_plan(
              run_id, plan_name, search_axes_json, source_groups_json, search_protocol_version
            ) VALUES(?,?,?,?,?)
            """,
            (
                run_id,
                plan_name,
                json.dumps(axes, ensure_ascii=False),
                json.dumps(source_groups, ensure_ascii=False),
                search_protocol_version,
            ),
        ).lastrowid
    )


def add_search_task(
    conn: sqlite3.Connection,
    run_id: int,
    search_plan_id: int,
    axis_key: str,
    source_group: str,
    query_text: str,
    status: str = "planned",
) -> int:
    return int(
        conn.execute(
            """
            INSERT INTO opportunity_search_task(
              run_id, search_plan_id, axis_key, source_group, query_text, search_task_status
            ) VALUES(?,?,?,?,?,?)
            """,
            (run_id, search_plan_id, axis_key, source_group, query_text, status),
        ).lastrowid
    )


def log_search_decision(
    conn: sqlite3.Connection,
    run_id: int,
    decision: str,
    title: str,
    search_task_id: int | None = None,
    url: str | None = None,
    publisher: str | None = None,
    reason: str | None = None,
    evidence_ref_uri: str | None = None,
) -> int:
    return int(
        conn.execute(
            """
            INSERT INTO opportunity_search_log(
              run_id, search_task_id, search_log_decision, title, url,
              publisher, reason, evidence_ref_uri
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (run_id, search_task_id, decision, title, url, publisher, reason, evidence_ref_uri),
        ).lastrowid
    )
