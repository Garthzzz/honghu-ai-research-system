from __future__ import annotations

import json
from pathlib import Path

from .audit import create_audit_issue
from .constants import DB_PATH
from .db import connect
from .early_signal import aggregate_run_early_signals
from .event_ledger import append_business_event
from .factor_dictionary import FACTORS, SEGMENT_FACTORS, factor_metadata
from .migrate import init_db
from .review_workflow import enqueue_review, record_agent_review
from .scoring import create_score_batch
from .search_models import add_search_task, create_search_plan, log_search_decision
from .workflow import advance_run, create_run, mark_reviewable

TABLE_DELETE_ORDER = [
    "opportunity_score_replay_record",
    "opportunity_state_transition",
    "opportunity_export_job",
    "opportunity_navigation_index",
    "opportunity_visual_evidence_link",
    "opportunity_visual_block",
    "opportunity_section_evidence_link",
    "opportunity_target_data_point",
    "opportunity_entity_investment_target",
    "opportunity_report_section",
    "opportunity_handoff_package",
    "opportunity_supplement_request",
    "opportunity_agent_review_log",
    "opportunity_review_queue",
    "opportunity_veto_status",
    "opportunity_market_reaction",
    "opportunity_audit_issue",
    "opportunity_event_ledger",
    "opportunity_early_signal_aggregate",
    "opportunity_composite_score",
    "opportunity_factor_score",
    "opportunity_slot_data_point_link",
    "opportunity_metric_slot",
    "opportunity_factor_readiness",
    "opportunity_ab_reference_link",
    "opportunity_data_point",
    "opportunity_claim_evidence",
    "opportunity_entity_mapping",
    "opportunity_candidate_entity",
    "opportunity_entity_maturation",
    "opportunity_score_batch",
    "opportunity_entity",
    "opportunity_source",
    "opportunity_intake_contract",
    "opportunity_source_discovery",
    "opportunity_source_cluster",
    "opportunity_search_log",
    "opportunity_search_task",
    "opportunity_search_plan",
    "opportunity_run_stats",
    "opportunity_run_manifest",
    "opportunity_run",
]


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _load_json(value: str | None, default=None):
    if not value:
        return {} if default is None else default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {} if default is None else default


def reset_fixture_rows(conn) -> None:
    conn.execute("PRAGMA foreign_keys=OFF")
    for table in TABLE_DELETE_ORDER:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM sqlite_sequence WHERE name LIKE 'opportunity_%'")
    conn.execute("PRAGMA foreign_keys=ON")


def _insert_sources(conn, run_id: int) -> None:
    conn.execute(
        """
        INSERT INTO opportunity_source_cluster(id, run_id, cluster_key, cluster_label, independence_rationale, confidence)
        VALUES
          (1, ?, 'official.synthetic.ir', '合成示例官方披露', '合成 fixture 的官方来源簇。', 0.95),
          (2, ?, 'media.synthetic.industry', '合成示例行业媒体', '合成 fixture 的媒体来源簇。', 0.70),
          (3, ?, 'rumor.synthetic.channel', '合成示例早期信号', '合成 fixture 的灰证据来源簇，仅用于 early signal。', 0.35)
        """,
        (run_id, run_id, run_id),
    )
    conn.execute(
        """
        INSERT INTO opportunity_source(
          id, run_id, source_cluster_id, title, source_tier, source_review_status,
          publisher, publish_date, url, excerpt, language, evidence_ref_uri,
          policy_evidence_role, policy_gate_verdict, scoring_eligibility
        ) VALUES
          (1, ?, 1, '合成示例 HBM 载板产能记录', 'A', 'pass', 'Fixture IR', '2026-06-30',
           'https://example.invalid/opportunity-lens/synthetic/hbm-substrate',
           '合成示例：交期超过 20 周，可认证产能仍受约束。',
           'zh-CN', 'opp://source/1', 'core_evidence', 'pass_core', 'core_eligible'),
          (2, ?, 2, '合成示例先进封装媒体核验', 'B', 'pass_with_note', 'Fixture Media', '2026-06-29',
           'https://example.invalid/opportunity-lens/synthetic/advanced-packaging',
           '合成示例：多家买方反馈载板供应偏紧，现货报价上行。',
           'zh-CN', 'opp://source/2', 'core_evidence', 'pass_core', 'core_eligible'),
          (3, ?, 3, '合成示例渠道早期信号', 'D', 'weak_source_only', 'Fixture Channel', '2026-07-01',
           'https://example.invalid/opportunity-lens/synthetic/early-signal',
           '合成示例：渠道传闻下游急单增加，但尚无官方或多源确认。',
           'zh-CN', 'opp://source/3', 'early_signal_candidate', 'pass_early_signal', 'early_signal_only')
        """,
        (run_id, run_id, run_id),
    )


def _insert_entities(conn, run_id: int) -> None:
    conn.execute(
        """
        INSERT INTO opportunity_entity(id, entity_type, taxonomy_level, canonical_name, display_name, description, external_ref_type)
        VALUES
          (1, 'product_material', 'product_material', '合成示例 HBM 载板产能', '合成示例 HBM 载板产能',
           '仅用于测试和页面 smoke 的产品/材料机会示例。', NULL),
          (2, 'company', 'company', '合成示例载板公司', '合成示例载板公司',
           '仅用于机会透镜 fixture 校验的公司示例。', NULL),
          (3, 'segment', 'segment', '先进封装载板环节', '先进封装载板环节',
           '用于分类和映射检查的合成父级环节。', NULL)
        """
    )
    conn.execute(
        """
        INSERT INTO opportunity_entity_maturation(run_id, entity_id, maturation_status, readiness_score, readiness_reason, evidence_ref_uri)
        VALUES
          (?, 1, 'scoring_ready', 0.88, '合成证据矩阵已足够进入评分。', 'opp://source/1'),
          (?, 2, 'scoring_limited', 0.66, '合成公司仍有一个 P1 证据缺口。', 'opp://source/2'),
          (?, 3, 'evidence_supported', 0.50, '仅作为合成父级环节。', 'opp://source/1')
        """,
        (run_id, run_id, run_id),
    )
    conn.execute(
        """
        INSERT INTO opportunity_candidate_entity(
          id, run_id, candidate_stage, name, entity_type_hint, entity_id,
          preliminary_research_priority_label, source_count, independent_source_count, reason, evidence_ref_uri
        ) VALUES
          (1, ?, 'merged_to_entity', '合成示例 HBM 载板产能', 'product_material', 1,
           'high_priority_for_scoring', 2, 2, '合成候选项已提升为规范实体。', 'opp://source/1'),
          (2, ?, 'merged_to_entity', '合成示例载板公司', 'company', 2,
           'medium_priority_for_followup', 2, 2, '合成公司候选项已提升为规范实体。', 'opp://source/2')
        """,
        (run_id, run_id),
    )
    conn.execute(
        """
        INSERT INTO opportunity_entity_mapping(
          run_id, source_entity_id, target_entity_id, mapping_type, relationship_status,
          review_status, evidence_ref_uri, rationale
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            2,
            1,
            "qualified_testing",
            "probable",
            "in_review",
            "opp://source/1",
            "合成 fixture 将公司映射到载板机会，并标注为认证测试状态。",
        ),
    )


def _insert_evidence(conn, run_id: int) -> None:
    claims = [
        (1, run_id, 1, 1, "capacity", "合成 HBM 载板交期超过 20 周。", "合成示例：交期超过 20 周。", "verified", "route_to_data_point", "supported", "opp://source/1"),
        (2, run_id, 1, 2, "price", "合成现货报价环比上升 18%。", "合成示例：现货报价上行。", "verified", "route_to_data_point", "supported", "opp://source/2"),
        (3, run_id, 2, 1, "company", "合成示例载板公司具备认证测试暴露，但尚不能证明已大批量供货。", "合成示例：可认证产能仍受约束。", "needs_review", "route_to_supplement_request", "partially_supported", "opp://source/1"),
        (4, run_id, 1, 3, "early_signal", "合成渠道传闻显示下游急单增加。", "合成示例：渠道传闻下游急单增加。", "weak_source_only", "use_as_background", "weak", "opp://source/3"),
    ]
    conn.executemany(
        """
        INSERT INTO opportunity_claim_evidence(
          id, run_id, entity_id, source_id, claim_type, claim_text, source_excerpt,
          claim_evidence_status, claim_next_action, support_status, evidence_ref_uri,
          policy_evidence_role, policy_gate_verdict, scoring_eligibility
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [row + (("early_signal_candidate", "pass_early_signal", "early_signal_only") if row[0] == 4 else ("core_evidence", "pass_core", "core_eligible")) for row in claims],
    )
    dps = [
        (1, run_id, 1, 1, "synthetic_lead_time", "2026Q2", None, 20.0, None, "周", "合成示例：交期超过 20 周。", "available", "pass", "manual_fixture", "opp://source/1"),
        (2, run_id, 1, 2, "synthetic_spot_quote_qoq", "2026Q2", None, 18.0, None, "%", "合成示例：现货报价上行 18%。", "available", "pass", "manual_fixture", "opp://source/2"),
        (3, run_id, 1, 1, "synthetic_supplier_count", "2026Q2", None, 3.0, None, "家", "合成示例：仅有三家经复核的可供供应商。", "available", "pass", "manual_fixture", "opp://source/1"),
        (4, run_id, 2, 1, "synthetic_revenue_exposure", "2026Q2", None, 32.0, None, "%", "合成示例：收入暴露代理值为 32%。", "available", "warning", "manual_fixture", "opp://source/1"),
        (5, run_id, 1, 3, "synthetic_channel_rush_order_signal", "2026Q3", None, 1.0, None, "信号", "合成示例：渠道传闻下游急单增加。", "weak_source_only", "warning", "manual_fixture", "opp://source/3"),
    ]
    conn.executemany(
        """
        INSERT INTO opportunity_data_point(
          id, run_id, entity_id, source_id, metric, period, as_of_date,
          value_num, value_text, unit, source_excerpt, value_status,
          calculation_review_status, extraction_method, evidence_ref_uri,
          policy_evidence_role, policy_gate_verdict, scoring_eligibility
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [row + (("early_signal_candidate", "pass_early_signal", "early_signal_only") if row[0] == 5 else ("core_evidence", "pass_core", "core_eligible")) for row in dps],
    )
    conn.execute(
        """
        INSERT INTO opportunity_ab_reference_link(
          run_id, local_object_type, local_object_id, evidence_ref_uri,
          ab_reference_usage, ab_snapshot_at, ab_reference_freshness_days, rationale
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            "source",
            1,
            "ab://research.source/1",
            "seed",
            "2026-07-02T00:00:00",
            7,
            "合成 fixture 保存一个只读 A/B 种子 URI，用于 resolver 测试。",
        ),
    )


def _insert_readiness_and_slots(conn, run_id: int) -> None:
    product_scores = [42, 58, 66, 74, 82, 49, 61, 72, 88, 93]
    company_scores = [36, 52, 64, 71, 79, 45, 59, 69, 84, 91, 68, 56, 73, 62]
    for idx, factor in enumerate(FACTORS, start=1):
        if factor in SEGMENT_FACTORS:
            status = "ready" if idx <= 8 else "limited"
            coverage = 0.88 if status == "ready" else 0.72
            confidence = 0.86 if status == "ready" else 0.76
        else:
            status = "not_applicable"
            coverage = confidence = 0.0
        conn.execute(
            """
            INSERT INTO opportunity_factor_readiness(
              run_id, entity_id, factor_code, factor_readiness_status,
              coverage, confidence, missing_reason, evidence_ref_uri_list_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (run_id, 1, factor.code, status, coverage, confidence, None, _j(["opp://source/1"])),
        )
    for idx, factor in enumerate(FACTORS, start=1):
        status = "ready" if idx <= 10 else "limited"
        conn.execute(
            """
            INSERT INTO opportunity_factor_readiness(
              run_id, entity_id, factor_code, factor_readiness_status,
              coverage, confidence, missing_reason, evidence_ref_uri_list_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (run_id, 2, factor.code, status, 0.72 if status == "ready" else 0.58, 0.76 if status == "ready" else 0.62, None, _j(["opp://source/2"])),
        )

    slot_id = 1
    for idx, factor in enumerate(SEGMENT_FACTORS):
        dp_id = (idx % 3) + 1
        conn.execute(
            """
            INSERT INTO opportunity_metric_slot(
              id, run_id, entity_id, factor_code, slot_key, slot_label, metric_name,
              metric_slot_status, value_status, slot_weight, slot_score, slot_confidence,
              unit, period, selected_data_point_id, evidence_ref_uri, notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                slot_id,
                run_id,
                1,
                factor.code,
                f"{factor.code}.primary",
                factor.label,
                factor.code,
                "accepted",
                "available",
                factor.weight,
                product_scores[idx],
                0.88 if idx < 8 else 0.76,
                "score",
                "2026Q2",
                dp_id,
                f"opp://data_point/{dp_id}",
                "合成 fixture 指标槽。",
            ),
        )
        conn.execute(
            """
            INSERT INTO opportunity_slot_data_point_link(slot_id, data_point_id, claim_id, link_role, evidence_ref_uri)
            VALUES(?,?,?,?,?)
            """,
            (slot_id, dp_id, 1 if dp_id == 1 else 2, "selected", f"opp://data_point/{dp_id}"),
        )
        slot_id += 1
    early_factor = SEGMENT_FACTORS[0]
    conn.execute(
        """
        INSERT INTO opportunity_metric_slot(
          id, run_id, entity_id, factor_code, slot_key, slot_label, metric_name,
          metric_slot_status, value_status, slot_weight, slot_score, slot_confidence,
          unit, period, selected_data_point_id, evidence_ref_uri,
          policy_evidence_role, policy_gate_verdict, scoring_eligibility, notes
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            slot_id,
            run_id,
            1,
            early_factor.code,
            f"{early_factor.code}.early_channel_signal",
            "渠道急单早期信号",
            "synthetic_channel_rush_order_signal",
            "weak_source_only",
            "weak_source_only",
            0.5,
            80,
            0.42,
            "signal",
            "2026Q3",
            5,
            "opp://data_point/5",
            "early_signal_candidate",
            "pass_early_signal",
            "early_signal_only",
            "合成 fixture：该槽只用于早期信号，不进入核心评分。",
        ),
    )
    conn.execute(
        """
        INSERT INTO opportunity_slot_data_point_link(slot_id, data_point_id, claim_id, link_role, evidence_ref_uri)
        VALUES(?,?,?,?,?)
        """,
        (slot_id, 5, 4, "early_signal", "opp://data_point/5"),
    )
    slot_id += 1
    for idx, factor in enumerate(FACTORS):
        dp_id = 4 if factor.code.startswith("company.") else ((idx % 3) + 1)
        conn.execute(
            """
            INSERT INTO opportunity_metric_slot(
              id, run_id, entity_id, factor_code, slot_key, slot_label, metric_name,
              metric_slot_status, value_status, slot_weight, slot_score, slot_confidence,
              unit, period, selected_data_point_id, evidence_ref_uri, notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                slot_id,
                run_id,
                2,
                factor.code,
                f"{factor.code}.primary",
                factor.label,
                factor.code,
                "accepted",
                "available",
                factor.weight,
                company_scores[idx],
                0.72 if idx < 10 else 0.62,
                "score",
                "2026Q2",
                dp_id,
                f"opp://data_point/{dp_id}",
                "合成 fixture 公司指标槽。",
            ),
        )
        conn.execute(
            """
            INSERT INTO opportunity_slot_data_point_link(slot_id, data_point_id, claim_id, link_role, evidence_ref_uri)
            VALUES(?,?,?,?,?)
            """,
            (slot_id, dp_id, 3 if dp_id == 4 else 1, "selected", f"opp://data_point/{dp_id}"),
        )
        slot_id += 1


def _insert_events_audit_review(conn, run_id: int) -> None:
    append_business_event(
        conn,
        run_id=run_id,
        entity_id=1,
        title="合成示例产能约束被记录",
        event_type="capacity_change",
        event_category="fundamental",
        event_direction="positive",
        summary="用于证明事件台账和去重行为的合成事件。",
        event_date="2026-06-30",
        dedupe_key="synthetic-hbm-substrate-capacity-2026q2",
        evidence_ref_uri="opp://source/1",
        score_effect="mapped_only",
        confidence=0.82,
    )
    append_business_event(
        conn,
        run_id=run_id,
        entity_id=1,
        title="合成示例重复产能记录",
        event_type="capacity_change",
        event_category="fundamental",
        event_direction="positive",
        summary="该重复事件使用同一去重键，不应创建第二条业务事件。",
        event_date="2026-06-30",
        dedupe_key="synthetic-hbm-substrate-capacity-2026q2",
        evidence_ref_uri="opp://source/2",
        score_effect="mapped_only",
        confidence=0.72,
    )
    issue_id = create_audit_issue(
        conn,
        run_id,
        affected_uri="opp://entity/2",
        issue_type="low_coverage",
        severity="p1",
        title="合成公司暴露仍需客户验证",
        detail="fixture 故意保留一个 P1 问题，用于验证黄色旗标和待复核行为。",
        entity_id=2,
        evidence_ref_uri="opp://source/1",
    )
    enqueue_review(conn, run_id, f"opp://audit_issue/{issue_id}", entity_id=2, audit_issue_id=issue_id)
    conn.execute(
        """
        INSERT INTO opportunity_supplement_request(
          id, run_id, entity_id, request_title, request_detail, priority,
          blocking_status, review_status, evidence_ref_uri
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            1,
            run_id,
            2,
            "验证合成客户认证状态",
            "合成补证请求：缺少直接客户证明。",
            "p1",
            "limits_scoring",
            "pending",
            "opp://audit_issue/1",
        ),
    )
    record_agent_review(conn, run_id, 1, "fixture_verifier", "GREEN", "resolved", "[]")


def _insert_reports_and_visuals(conn, run_id: int, score_batch_id: int) -> None:
    comp = conn.execute(
        "SELECT id FROM opportunity_composite_score WHERE run_id=? AND entity_id=1 AND score_batch_id=?",
        (run_id, score_batch_id),
    ).fetchone()
    comp_uri = f"opp://composite_score/{comp['id']}"
    conn.execute(
        """
        INSERT INTO opportunity_report_section(
          id, run_id, entity_id, section_key, section_title, body_markdown,
          support_status, red_flag_level, flag_derivation_source, flag_reason_json,
          review_status, evidence_ref_uri_list_json, sort_order
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            1,
            run_id,
            1,
            "executive_summary",
            "合成机会摘要",
            (
                "### 研究对象\n\n"
                "这个合成实体用于验证 Opportunity Lens 的实体研究页、评分、证据和标的链接，不是真实行业结论。\n\n"
                "### 证据和数据\n\n"
                "合成数据包括交期、现货报价、供应商数量和渠道急单信号，均可回到 fixture 来源和数据点。\n\n"
                "### 分析\n\n"
                "该实体只验证供需失衡分析页面能否把证据、评分、审计和标的研究入口连起来，不能用于真实投资判断。\n\n"
                "### 总结\n\n"
                "合成 fixture 的价值是回归测试。真实研究必须替换为可核验的一手或 A/B 行研证据，并补具体标的暴露逻辑。\n\n"
                "### 相关标的与投资研究建议\n\n"
                "合成示例载板公司只用于测试实体到标的的链接。证实时只验证字段渲染和链路可达，证伪时阻断回归发布。"
            ),
            "supported",
            "none",
            "system",
            _j([]),
            "approved",
            _j(["opp://source/1", comp_uri]),
            1,
        ),
    )
    conn.execute(
        "INSERT INTO opportunity_section_evidence_link(section_id, evidence_ref_uri, link_role) VALUES(?,?,?)",
        (1, "opp://source/1", "supports"),
    )
    cur = conn.execute(
        """
        INSERT INTO opportunity_entity_investment_target(
          run_id, entity_id, target_name, ticker, market, target_type, company_id, target_url,
          exposure_rationale, evidence_ref_uri, research_action, investment_view, risk_note,
          target_priority, target_quality_label, relative_preference,
          confirmed_scenario_action, falsified_scenario_action,
          target_profile_markdown, target_deep_research_markdown, entity_relation_markdown,
          parent_research_relation_markdown, conditional_investment_recommendation,
          financial_data_status, link_status, support_status, sort_order
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            1,
            "合成示例载板公司",
            None,
            "合成市场",
            "company",
            None,
            "/opportunity-lens/entity/2",
            "该公司是 fixture 中映射到载板产能约束的合成主体，只用于验证实体到标的的展示链路。",
            "opp://source/1",
            "补客户认证、量产交付和真实财务暴露后才允许进入真实投资研究。",
            "仅作页面和 API 回归样例，不构成真实标的建议。",
            "合成 fixture 不可交易，也不能推导真实投资结论。",
            "P3 回归样例",
            "不适用",
            "仅用于验证实体到标的字段展示，不参与同实体内优先级比较。",
            "若测试数据完整，应只确认页面链路和字段渲染正常。",
            "若证据缺失或页面字段为空，应阻断发布回归。",
            "### 标的介绍\n\n合成示例载板公司是 Opportunity Lens fixture 中的测试标的，不对应真实证券。\n\n### 数据和证据\n\n证据来自 fixture source 与合成数据点，用于验证页面是否展示来源、时间、原文和条件化动作。",
            "### 深入研究\n\n该标的的研究重点是页面、API、溯源和条件化建议是否闭环，不用于真实投资判断。",
            "该标的映射到合成 HBM 载板实体，用于验证实体和标的之间的暴露关系。",
            "该标的是合成扫描任务的一部分，用于验证主问题、实体、因子和标的页面是否可追溯。",
            "证实时确认页面链路和字段渲染正常；证伪时阻断回归发布并补字段。",
            "合成 fixture 无真实财务数据；真实研究新增财务和市场快照只能接入 Tushare、yfinance 或 A/B company_profile。历史 Wind 溯源仅可作为旧数据事实保留。",
            "not_applicable",
            "not_applicable",
            1,
        ),
    )
    target_id = int(cur.lastrowid)
    target_points = [
        ("标的与研究实体关系强度", "relationship", "该标的是合成实体的回归测试映射。", "中性", "mixed", 10),
        ("证实情景动作", "scenario_confirm", "页面链路、来源抽屉和条件化建议均可渲染时，fixture 通过。", "条件化建议", "positive", 20),
        ("证伪情景动作", "scenario_falsify", "任何必填字段缺失、证据不可点或页面 500 时，fixture 阻断。", "条件化建议", "negative", 30),
    ]
    for metric_name, category, value_text, quality, direction, sort_order in target_points:
        direction_score = {"positive": 1.0, "negative": -1.0, "mixed": 0.0}.get(direction, 0.0)
        conn.execute(
            """
            INSERT INTO opportunity_target_data_point(
              run_id, entity_id, target_id, metric_name, metric_category,
              value_text, unit, source_title, source_publisher, source_excerpt,
              evidence_ref_uri, data_quality_label, direction, credibility_weight,
              numeric_weight, direction_score, weighted_contribution, sort_order
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                1,
                target_id,
                metric_name,
                category,
                value_text,
                "文本",
                "合成 fixture 研究包",
                "Opportunity Lens",
                value_text,
                "opp://source/1",
                quality,
                direction,
                0.7,
                0.7,
                direction_score,
                round(0.7 * 0.7 * direction_score, 4),
                sort_order,
            ),
        )
    factors = conn.execute(
        """
        SELECT id, factor_code, score_adjusted, coverage, confidence
        FROM opportunity_factor_score
        WHERE score_batch_id=? AND entity_id=1
        ORDER BY factor_code
        """,
        (score_batch_id,),
    ).fetchall()
    factor_visual_rows = []
    factor_display_rows = []
    for row in factors:
        item = dict(row)
        item.update(factor_metadata(row["factor_code"]))
        trace = _load_json(conn.execute(
            "SELECT factor_trace_json FROM opportunity_factor_score WHERE id=?",
            (row["id"],),
        ).fetchone()["factor_trace_json"])
        trace["evidence_weighting"] = {
            "minimum_required_refs": 3,
            "available_ref_count": 3,
            "gate_verdict": "通过",
            "reason": "合成 fixture 提供三条可追溯证据，用于验证证据数量闸门展示。",
            "items": [
                {
                    "ref": "opp://source/1",
                    "credibility_weight": 0.8,
                    "numeric_weight": 0.8,
                    "direction": "positive",
                    "direction_score": 1.0,
                    "weighted_contribution": 0.64,
                    "reason": "合成来源 1 支撑供给瓶颈。",
                },
                {
                    "ref": "opp://source/2",
                    "credibility_weight": 0.7,
                    "numeric_weight": 0.8,
                    "direction": "positive",
                    "direction_score": 1.0,
                    "weighted_contribution": 0.56,
                    "reason": "合成来源 2 支撑价格信号。",
                },
                {
                    "ref": "opp://source/3",
                    "credibility_weight": 0.6,
                    "numeric_weight": 0.7,
                    "direction": "mixed",
                    "direction_score": 0.0,
                    "weighted_contribution": 0.0,
                    "reason": "合成来源 3 用于风险和反证。",
                },
            ],
        }
        conn.execute(
            """
            UPDATE opportunity_factor_score
            SET factor_trace_json=?, evidence_ref_uri_list_json=?
            WHERE id=?
            """,
            (_j(trace), _j(["opp://source/1", "opp://source/2", "opp://source/3"]), row["id"]),
        )
        factor_visual_rows.append(item)
        factor_display_rows.append(
            [
                item["factor_label"],
                item["factor_code"],
                item["factor_formula"],
                row["score_adjusted"],
                row["coverage"],
                row["confidence"],
            ]
        )
    visuals = [
        (
            1,
            run_id,
            None,
            1,
            "run_kpi",
            "kpi",
            "扫描 KPI",
            "合成 C 轨 fixture",
            _j({"来源": 2, "实体": 3, "已评分": 2, "待处理P1": 1}),
            _j({"table": [["来源", 2], ["实体", 3], ["已评分", 2], ["待处理P1", 1]]}),
            _j(["opp://source/1", "opp://source/2"]),
            "supported",
            "yellow",
            None,
            1,
        ),
        (
            2,
            run_id,
            1,
            1,
            "factor_heatmap",
            "heatmap",
            "因子评分热力图",
            "合成产品/材料因子",
            _j({"factors": factor_visual_rows}),
            _j({
                "columns": ["因子中文名", "因子代码", "计算公式", "调整后分数", "覆盖度", "置信度"],
                "rows": factor_display_rows,
            }),
            _j([f"opp://factor_score/{r['id']}" for r in factors]),
            "supported",
            "none",
            None,
            2,
        ),
        (
            3,
            run_id,
            1,
            1,
            "event_timeline",
            "timeline",
            "事件时间线",
            "合成事件台账",
            _j({"events": [{"date": "2026-06-30", "title": "合成示例产能约束被记录"}]}),
            _j({"rows": [["2026-06-30", "合成示例产能约束被记录"]]}),
            _j(["opp://event/2"]),
            "supported",
            "none",
            None,
            3,
        ),
    ]
    conn.executemany(
        """
        INSERT INTO opportunity_visual_block(
          id, run_id, entity_id, section_id, block_key, block_type, title, subtitle,
          data_json, print_fallback_json, evidence_ref_uri_list_json, support_status,
          red_flag_level, empty_state_reason, sort_order
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        visuals,
    )
    for row in factors:
        conn.execute(
            """
            INSERT INTO opportunity_visual_evidence_link(
              visual_block_id, evidence_ref_uri, factor_score_id
            ) VALUES(?,?,?)
            """,
            (2, f"opp://factor_score/{row['id']}", row["id"]),
        )
    conn.execute(
        """
        INSERT INTO opportunity_handoff_package(run_id, handoff_status, package_json, gap_summary)
        VALUES(?,?,?,?)
        """,
        (
            run_id,
            "scoring_limited",
            _j({"run_id": run_id, "score_batch_id": score_batch_id, "fixture": True}),
            "仍有一个合成公司 P1 补证请求未关闭。",
        ),
    )
    conn.executemany(
        """
        INSERT INTO opportunity_navigation_index(run_id, entity_id, section_id, nav_key, label, href, sort_order)
        VALUES(?,?,?,?,?,?,?)
        """,
        [
            (run_id, None, None, "overview", "总览", f"/opportunity-lens/run/{run_id}", 1),
            (run_id, None, None, "entities", "机会实体", f"/opportunity-lens/run/{run_id}/entities", 2),
            (run_id, None, None, "audit", "审计", f"/opportunity-lens/run/{run_id}/audit", 3),
            (run_id, None, None, "export", "导出", f"/opportunity-lens/run/{run_id}/export", 4),
        ],
    )


def _update_stats(conn, run_id: int) -> None:
    stats = {
        "source_count": conn.execute("SELECT COUNT(*) FROM opportunity_source WHERE run_id=?", (run_id,)).fetchone()[0],
        "independent_source_count": conn.execute("SELECT COUNT(*) FROM opportunity_source_cluster WHERE run_id=?", (run_id,)).fetchone()[0],
        "candidate_count": conn.execute("SELECT COUNT(*) FROM opportunity_candidate_entity WHERE run_id=?", (run_id,)).fetchone()[0],
        "canonical_entity_count": conn.execute("SELECT COUNT(*) FROM opportunity_entity_maturation WHERE run_id=?", (run_id,)).fetchone()[0],
        "scored_entity_count": conn.execute("SELECT COUNT(*) FROM opportunity_composite_score WHERE run_id=? AND is_current=1", (run_id,)).fetchone()[0],
        "open_p0_count": conn.execute("SELECT COUNT(*) FROM opportunity_audit_issue WHERE run_id=? AND audit_severity='p0' AND audit_issue_status IN ('open','in_review','reopened')", (run_id,)).fetchone()[0],
        "open_p1_count": conn.execute("SELECT COUNT(*) FROM opportunity_audit_issue WHERE run_id=? AND audit_severity='p1' AND audit_issue_status IN ('open','in_review','reopened')", (run_id,)).fetchone()[0],
        "supplement_open_count": conn.execute("SELECT COUNT(*) FROM opportunity_supplement_request WHERE run_id=? AND review_status IN ('pending','in_review','reopened')", (run_id,)).fetchone()[0],
    }
    conn.execute(
        """
        UPDATE opportunity_run_stats
        SET source_count=?, independent_source_count=?, candidate_count=?,
            canonical_entity_count=?, scored_entity_count=?, open_p0_count=?,
            open_p1_count=?, supplement_open_count=?, updated_at=datetime('now')
        WHERE run_id=?
        """,
        (
            stats["source_count"],
            stats["independent_source_count"],
            stats["candidate_count"],
            stats["canonical_entity_count"],
            stats["scored_entity_count"],
            stats["open_p0_count"],
            stats["open_p1_count"],
            stats["supplement_open_count"],
            run_id,
        ),
    )


def load_synthetic_fixture(db_path: str | Path = DB_PATH, reset: bool = True) -> int:
    init_db(db_path, reset=False)
    conn = connect(db_path)
    try:
        reset_fixture_rows(conn)
        run_id = create_run(
            conn,
            question="合成 HBM 载板供需失衡扫描",
            run_mode="c_open_with_seed",
            requested_by="synthetic_fixture",
            problem_statement="仅用于机会透镜验证的合成 fixture。",
        )
        for status, reason in [
            ("intake_validated", "合成需求已受理。"),
            ("searching", "合成本地检索计划已打开。"),
        ]:
            advance_run(conn, run_id, status, reason)
        plan_id = create_search_plan(
            conn,
            run_id,
            "合成本地 fixture 检索计划",
            axes=[
                {"axis_key": "demand", "label": "需求信号"},
                {"axis_key": "supply", "label": "供给约束"},
                {"axis_key": "signal", "label": "价格/市场信号"},
            ],
            source_groups=["official", "media", "ab_seed"],
        )
        task1 = add_search_task(conn, run_id, plan_id, "supply", "official", "合成本地 fixture 供给", "completed")
        task2 = add_search_task(conn, run_id, plan_id, "signal", "media", "合成本地 fixture 定价", "completed")
        log_search_decision(conn, run_id, "included", "合成示例 HBM 载板产能记录", task1, publisher="Fixture IR")
        log_search_decision(conn, run_id, "included", "合成示例先进封装媒体核验", task2, publisher="Fixture Media")
        advance_run(conn, run_id, "screening", "合成检索任务已完成。")
        _insert_sources(conn, run_id)
        advance_run(conn, run_id, "extracting", "合成来源已纳入。")
        _insert_entities(conn, run_id)
        _insert_evidence(conn, run_id)
        advance_run(conn, run_id, "mapping_entities", "合成 claim 已抽取并完成实体映射。")
        _insert_readiness_and_slots(conn, run_id)
        _insert_events_audit_review(conn, run_id)
        advance_run(conn, run_id, "scoring", "合成指标槽已准备评分。")
        score_batch_id = create_score_batch(conn, run_id)
        aggregate_run_early_signals(conn, run_id)
        advance_run(conn, run_id, "report_drafting", "合成评分批次已完成。")
        _insert_reports_and_visuals(conn, run_id, score_batch_id)
        advance_run(conn, run_id, "under_review", "合成报告段落已生成。")
        advance_run(conn, run_id, "completed", "合成 fixture 复核通过，未发现 P0 阻塞。")
        mark_reviewable(conn, run_id)
        _update_stats(conn, run_id)
        conn.commit()
        return run_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    run_id = load_synthetic_fixture(DB_PATH, reset=True)
    print(f"已加载机会透镜合成 fixture，run_id={run_id}")


if __name__ == "__main__":
    main()
