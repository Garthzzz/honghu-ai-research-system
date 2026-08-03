from __future__ import annotations

import sqlite3

import pytest

from tools.maintenance.backfill_opportunity_factor_missing_reasons import collect_updates
from tools.opportunity_lens.silicon_run_pack_support import (
    SEGMENT_FACTOR_CODES,
    _SEGMENT_SLOT_PROTOCOL,
    _protocol_metric_slots,
    _slot_factor_calculation,
    normalize_agent_data_points,
)
from tools.opportunity_lens.run_pack_contract import (
    PackValidationReport,
    _validate_metric_slot_chain,
)


def _source(ref: str, text: str, *, tier: str = "S") -> dict:
    return {
        "ref": ref,
        "title": text,
        "title_zh": text,
        "excerpt": text,
        "excerpt_zh": text,
        "source_tier": tier,
        "source_review_status": "pass",
        "independence_key": f"independent-{ref}",
    }


def test_protocol_defines_weighted_slots_for_every_segment_factor() -> None:
    assert set(_SEGMENT_SLOT_PROTOCOL) == set(SEGMENT_FACTOR_CODES)
    for factor_code, slots in _SEGMENT_SLOT_PROTOCOL.items():
        assert sum(float(slot["weight"]) for slot in slots) == pytest.approx(1.0)
        assert len({slot["code"] for slot in slots}) == len(slots), factor_code


def test_unmatched_source_does_not_fill_price_slots() -> None:
    sources = {
        f"S{index}": _source(f"S{index}", "官方披露新工厂开工和资本开支预算")
        for index in range(1, 6)
    }
    slots = _protocol_metric_slots(
        key="test_entity",
        code="demand.downstream_price_momentum",
        expert_bucket_score=82.0,
        source_refs=list(sources),
        sources_by_ref=sources,
        item={"period": "2026"},
    )
    assert all(slot["value_status"] == "not_found_after_search" for slot in slots)
    result = _slot_factor_calculation(
        key="test_entity",
        code="demand.downstream_price_momentum",
        raw_slots=slots,
        sources_by_ref=sources,
        audit_multiplier=1.0,
    )
    assert result["coverage"] == 0.0
    assert result["score_raw"] == 50.0
    assert result["score_adjusted"] == 50.0
    assert result["score_status"] == "insufficient_evidence"
    assert "下游产品三个月价格变化" in result["missing_reason"]


def test_partial_slot_coverage_converges_toward_neutral() -> None:
    sources = {"S1": _source("S1", "官方披露三个月合同价格明显上涨")}
    slots = [
        {
            "slot_code": "primary",
            "slot_label": "主指标",
            "slot_role": "primary",
            "slot_weight": 0.6,
            "slot_score": 90.0,
            "value_status": "available",
            "source_refs": ["S1"],
            "data_point_keys": ["DP1"],
            "raw_value_text": "三个月合同价格明显上涨",
            "raw_unit": "%",
            "standardized_value_text": "强正向",
            "standardized_unit": "%",
            "normalization_method": "同品类三个月合同价格变化分档",
            "bucket": "强正向",
            "scoring_rule": "三个月价格涨幅达到30%以上计90分",
            "preprocess_trace": "保持同品类、同报价口径并统一成三个月百分比变化。",
            "scoring_trace": "标准化涨幅按冻结区间映射为90分。",
        },
        {
            "slot_code": "support",
            "slot_label": "辅助指标",
            "slot_role": "supporting",
            "slot_weight": 0.4,
            "value_status": "not_found_after_search",
            "source_refs": [],
        },
    ]
    result = _slot_factor_calculation(
        key="test_entity",
        code="demand.downstream_price_momentum",
        raw_slots=slots,
        sources_by_ref=sources,
        audit_multiplier=1.0,
    )
    assert result["coverage"] == pytest.approx(0.6)
    assert result["score_raw"] == pytest.approx(90.0)
    assert 50.0 < result["score_adjusted"] < result["score_raw"]
    assert result["adjustment_trace"]["coverage_multiplier"] == pytest.approx(0.6)
    assert result["adjustment_trace"]["factor_reliability_multiplier"] <= 0.6


def test_context_slot_never_improves_factor_coverage_or_confidence() -> None:
    sources = {"S1": _source("S1", "公司披露远期规划产能，但尚未开工")}
    slots = [
        {
            "slot_code": "primary",
            "slot_label": "已开工或在建产能",
            "slot_role": "primary",
            "slot_weight": 0.9,
            "value_status": "not_found_after_search",
            "source_refs": [],
        },
        {
            "slot_code": "planned_or_rumored_capacity",
            "slot_label": "仅规划或传闻产能",
            "slot_role": "context",
            "slot_weight": 0.1,
            "value_status": "available",
            "source_refs": ["S1"],
            "data_point_keys": ["DP-CONTEXT-1"],
            "raw_value_num": 20.0,
            "raw_unit": "万片/月",
            "standardized_value_num": 20.0,
            "standardized_unit": "万片/月",
            "normalization_method": "保持公司规划的月产能口径，仅作背景展示",
            "preprocess_trace": "核对主体、计划状态和月产能单位，不将规划当成在建产能。",
        },
    ]
    result = _slot_factor_calculation(
        key="test_entity",
        code="supply.capacity_pipeline",
        raw_slots=slots,
        sources_by_ref=sources,
        audit_multiplier=1.0,
    )
    assert result["coverage"] == 0.0
    assert result["confidence"] == 0.0
    assert result["score_raw"] == 50.0
    assert result["score_adjusted"] == 50.0
    assert result["score_status"] == "insufficient_evidence"
    assert result["missing_reason"] == "缺少可直接复算的已开工或在建产能。"
    context = result["metric_slots"][1]
    assert not {"slot_score", "bucket", "scoring_rule"} & set(context)
    assert "不进入因子分数、覆盖率或置信度" in context["scoring_trace"]


def test_context_slot_rejects_any_score() -> None:
    sources = {"S1": _source("S1", "公司披露远期规划产能")}
    with pytest.raises(ValueError, match="context槽不得设置slot_score"):
        _slot_factor_calculation(
            key="test_entity",
            code="supply.capacity_pipeline",
            raw_slots=[
                {
                    "slot_code": "planned_or_rumored_capacity",
                    "slot_role": "context",
                    "slot_weight": 0.1,
                    "slot_score": 95.0,
                    "value_status": "available",
                    "source_refs": ["S1"],
                    "data_point_keys": ["DP-CONTEXT-1"],
                    "raw_value_num": 20.0,
                    "raw_unit": "万片/月",
                    "standardized_value_num": 20.0,
                    "standardized_unit": "万片/月",
                    "normalization_method": "保持月产能口径",
                    "preprocess_trace": "核对主体与单位。",
                }
            ],
            sources_by_ref=sources,
            audit_multiplier=1.0,
        )


def test_run_pack_contract_excludes_context_from_coverage() -> None:
    context = {
        "slot_code": "planned_or_rumored_capacity",
        "slot_role": "context",
        "slot_weight": 0.1,
        "value_status": "available",
        "data_point_keys": ["DP1"],
        "source_refs": ["S1"],
        "raw_value_num": 20.0,
        "raw_unit": "万片/月",
        "standardized_value_num": 20.0,
        "standardized_unit": "万片/月",
        "normalization_method": "保持月产能口径",
        "preprocess_trace": "核对主体、计划状态和单位。",
        "scoring_trace": "该槽只展示背景事实，不进入因子分数、覆盖率或置信度。",
    }
    report = PackValidationReport("opportunity_lens.run_pack.v2", "research.workflow.v2", "validate")
    _validate_metric_slot_chain(
        report,
        {"coverage": 0.0, "score_status": "insufficient_evidence", "metric_slots": [context]},
        path="entities[0].factor_scores[0]",
        data_point_keys={"DP1"},
        source_groups={"S1": "issuer:S1"},
    )
    assert not report.issues

    scored_context = dict(context, slot_score=95.0)
    invalid = PackValidationReport("opportunity_lens.run_pack.v2", "research.workflow.v2", "validate")
    _validate_metric_slot_chain(
        invalid,
        {"coverage": 0.0, "score_status": "insufficient_evidence", "metric_slots": [scored_context]},
        path="entities[0].factor_scores[0]",
        data_point_keys={"DP1"},
        source_groups={"S1": "issuer:S1"},
    )
    assert {issue.code for issue in invalid.issues} == {"metric_slot_chain"}

    classified_context = dict(context, bucket="背景信息", scoring_rule="不计分")
    invalid_classification = PackValidationReport(
        "opportunity_lens.run_pack.v2", "research.workflow.v2", "validate"
    )
    _validate_metric_slot_chain(
        invalid_classification,
        {
            "coverage": 0.0,
            "score_status": "insufficient_evidence",
            "metric_slots": [classified_context],
        },
        path="entities[0].factor_scores[0]",
        data_point_keys={"DP1"},
        source_groups={"S1": "issuer:S1"},
    )
    assert {issue.code for issue in invalid_classification.issues} == {
        "metric_slot_chain"
    }

    overstated = PackValidationReport("opportunity_lens.run_pack.v2", "research.workflow.v2", "validate")
    _validate_metric_slot_chain(
        overstated,
        {"coverage": 1.0, "score_status": "complete", "metric_slots": [context]},
        path="entities[0].factor_scores[0]",
        data_point_keys={"DP1"},
        source_groups={"S1": "issuer:S1"},
    )
    assert {issue.code for issue in overstated.issues} == {"metric_slot_coverage"}


def test_explicit_slot_requires_data_point_to_standardization_to_score_chain() -> None:
    sources = {"S1": _source("S1", "官方披露客户资本开支同比增长30%")}
    item = {
        "period": "2026",
        "candidate_data_points": [
            {
                "data_point_key": "DP-CAPEX-1",
                "data_point_title": "客户资本开支同比变化",
                "metric": "资本开支同比变化",
                "period": "2026",
                "value_num": 30.0,
                "unit": "%",
                "source_ref": "S1",
            }
        ],
        "metric_slot_inputs": {
            "customer_capex_yoy_or_guidance": {
                "data_point_keys": ["DP-CAPEX-1"],
                "standardized_value_num": 30.0,
                "standardized_unit": "%",
                "normalization_method": "保持同比百分比口径，不做币种换算",
                "bucket": "重大扩产",
                "slot_score": 95.0,
                "scoring_rule": "CapEx同比增长25%以上计90—100分，本次固定为95分",
            }
        },
    }
    slots = _protocol_metric_slots(
        key="test_entity",
        code="demand.customer_capex_capacity_signal",
        expert_bucket_score=10.0,
        source_refs=["S1"],
        sources_by_ref=sources,
        item=item,
    )
    capex = next(slot for slot in slots if slot["slot_code"] == "customer_capex_yoy_or_guidance")
    assert capex["raw_value_num"] == 30.0
    assert capex["standardized_value_num"] == 30.0
    assert capex["slot_score"] == 95.0
    assert capex["data_point_keys"] == ["DP-CAPEX-1"]
    assert all(
        slot["value_status"] == "not_found_after_search"
        for slot in slots
        if slot["slot_code"] != "customer_capex_yoy_or_guidance"
    )


def test_usable_slot_without_replay_chain_is_rejected() -> None:
    sources = {"S1": _source("S1", "官方披露价格上涨")}
    with pytest.raises(ValueError, match="数据点链接"):
        _slot_factor_calculation(
            key="test_entity",
            code="demand.downstream_price_momentum",
            raw_slots=[
                {
                    "slot_code": "downstream_price_3m_change",
                    "slot_role": "primary",
                    "slot_weight": 1.0,
                    "slot_score": 70.0,
                    "value_status": "available",
                    "source_refs": ["S1"],
                    "raw_value_num": 10.0,
                    "raw_unit": "%",
                    "standardized_value_num": 10.0,
                    "standardized_unit": "%",
                    "normalization_method": "同品类三个月百分比变化",
                    "bucket": "+5%至+15%",
                    "scoring_rule": "+5%至+15%计70分",
                }
            ],
            sources_by_ref=sources,
            audit_multiplier=1.0,
        )


def test_run_pack_contract_rejects_incomplete_or_mismatched_slot_chain() -> None:
    slot = {
        "slot_code": "customer_capex_yoy_or_guidance",
        "slot_weight": 1.0,
        "value_status": "available",
        "data_point_keys": ["DP1"],
        "source_refs": ["S1"],
        "raw_value_num": 30.0,
        "raw_unit": "%",
        "standardized_value_num": 30.0,
        "standardized_unit": "%",
        "normalization_method": "保持同比百分比口径",
        "bucket": "重大扩产",
        "scoring_rule": "同比增长25%以上计90—100分",
        "preprocess_trace": "已核对期间与百分比口径。",
        "scoring_trace": "30%落入25%以上分档，对应95分。",
        "slot_score": 95.0,
    }
    valid = PackValidationReport("opportunity_lens.run_pack.v2", "research.workflow.v2", "validate")
    _validate_metric_slot_chain(
        valid,
        {"coverage": 1.0, "score_status": "complete", "metric_slots": [slot]},
        path="entities[0].factor_scores[0]",
        data_point_keys={"DP1"},
        source_groups={"S1": "issuer:S1"},
    )
    assert not valid.issues

    broken = PackValidationReport("opportunity_lens.run_pack.v2", "research.workflow.v2", "validate")
    bad_slot = dict(slot)
    bad_slot.pop("scoring_rule")
    _validate_metric_slot_chain(
        broken,
        {"coverage": 0.8, "score_status": "complete", "metric_slots": [bad_slot]},
        path="entities[0].factor_scores[0]",
        data_point_keys={"DP1"},
        source_groups={"S1": "issuer:S1"},
    )
    assert {issue.code for issue in broken.issues} == {"metric_slot_chain", "metric_slot_coverage"}


def test_data_point_normalization_preserves_forecast_plan_and_inference_types() -> None:
    sources = {"S1": _source("S1", "官方项目资料")}
    rows = [
        {"data_point_id": "DP1", "subject": "行业", "metric": "产能", "period": "2028E", "value": 10, "unit": "万片/月", "source_id": "S1", "fact_type": "fact", "note": "SEMI公开预测。"},
        {"data_point_id": "DP2", "subject": "公司", "metric": "设计产能", "period": "项目口径", "value": 20, "unit": "万片/月", "source_id": "S1", "fact_type": "fact", "note": "公司规划目标。"},
        {"data_point_id": "DP3", "subject": "模型", "metric": "换算值", "period": "2028", "value": 30, "unit": "万片/月", "source_id": "S1", "fact_type": "inferred", "note": "按公开输入计算。"},
    ]
    points = normalize_agent_data_points(rows, sources_by_ref=sources)
    assert [point["data_point_key"] for point in points] == ["DP1", "DP2", "DP3"]
    assert [point["research_category"] for point in points] == [
        "industry_or_company_forecast",
        "company_plan_or_target",
        "calculated_inference",
    ]


def test_missing_reason_backfill_only_fills_blank_rows() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE opportunity_factor_readiness (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            factor_code TEXT NOT NULL,
            missing_reason TEXT
        );
        CREATE TABLE opportunity_metric_slot (
            run_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            factor_code TEXT NOT NULL,
            slot_key TEXT NOT NULL,
            slot_label TEXT,
            metric_name TEXT,
            value_status TEXT,
            slot_score REAL,
            scoring_eligibility TEXT
        );
        INSERT INTO opportunity_factor_readiness
            (id, run_id, entity_id, factor_code, missing_reason)
        VALUES
            (1, 10, 100, 'supply.capacity_pipeline', '人工核验后保留的缺口说明。'),
            (2, 10, 101, 'supply.capacity_pipeline', NULL);
        INSERT INTO opportunity_metric_slot
            (run_id, entity_id, factor_code, slot_key, slot_label,
             value_status, slot_score, scoring_eligibility)
        VALUES
            (10, 100, 'supply.capacity_pipeline', 'commissioned_capacity',
             '已投产产能', 'not_found_after_search', NULL, 'core_eligible'),
            (10, 101, 'supply.capacity_pipeline', 'commissioned_capacity',
             '已投产产能', 'not_found_after_search', NULL, 'core_eligible');
        """
    )

    updates = collect_updates(conn, [10])

    assert [item["id"] for item in updates] == [2]
    assert updates[0]["after"] == "缺少可直接复算的已投产产能。"
    conn.close()
