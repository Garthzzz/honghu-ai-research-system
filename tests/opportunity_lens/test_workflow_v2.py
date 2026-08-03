from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.opportunity_lens.constants import RESEARCH_WORKFLOW_CONTRACT_VERSION, RUN_PACK_SCHEMA_VERSION
from tools.opportunity_lens.db import connect
from tools.opportunity_lens.manual_run_loader import load_pack, validate_pack_file
from tools.opportunity_lens.public_content_quality_audit import (
    PUBLIC_AUDIT_FIELD,
    build_pack_audit_attestation,
)
from tools.opportunity_lens.publication import evaluate_publication_gate
from tools.opportunity_lens.run_pack_contract import validate_run_pack
from tools.opportunity_lens.scoring import create_score_batch
from tools.opportunity_lens.workflow_bridge import build_pack_workflow_state

from helpers import FixtureDBTestCase


HASH = "sha256:" + "a" * 64


def long_text(seed: str, minimum: int) -> str:
    paragraph = (
        f"{seed}要回答的问题是如何把资料事实、口径边界、计算过程、反方证据和使用限制连接起来。"
        "结论只覆盖已有证据能够支持的范围。"
        "关键限制已经在本轮分析中说明，并据此降低结论置信度。"
    )
    return (paragraph + "\n\n") * (minimum // len(paragraph) + 3)


def build_theory_pack(*, include_reviews: bool = True) -> dict:
    source = {
        "ref": "official_1",
        "title": "官方研究资料",
        "title_zh": "官方研究资料",
        "publisher": "官方机构",
        "publish_date": "2026-07-01",
        "event_date": "2026-06-30",
        "fetch_date": "2026-07-12",
        "local_locator": "原文P3，方法表第一行",
        "source_tier": "S",
        "source_review_status": "pass",
        "excerpt": "官方资料给出研究方法与观测口径。",
        "excerpt_zh": "官方资料给出研究方法与观测口径。",
        "language": "zh-CN",
        "url": "https://example.com/official-method",
        "independence_key": "official_method_20260701",
        "independence_rationale": "直接来自官方原始材料，不是二手转述。",
    }
    research_points = [
        {
            "source_ref": "official_1",
            "data_point_title": f"研究底稿 {index}",
            "research_category": "method",
            "metric": f"研究指标 {index}",
            "period": "2026",
            "value_text": f"结果 {index}",
            "unit": "文本",
            "source_excerpt": f"官方资料中的第 {index} 项原文事实。",
            "interpretation": f"第 {index} 项事实用于界定研究对象的第 {index} 个边界。",
            "research_use": f"在复算流程第 {index} 步校准输入并检查反例。",
        }
        for index in range(1, 9)
    ]
    entity = {
        "key": "theory_entity",
        "canonical_name": "理论研究实体",
        "display_name": "理论研究实体",
        "entity_type": "product_material",
        "taxonomy_level": "product_material",
        "description": "用于验证理论研究实体的口径、底稿和发布门禁。",
        "entity_research_mode": "theory_research",
        "research_profile": {
            "research_question": "如何定义并复算该研究指标？",
            "research_scope": "方法、口径和限制。",
            "methodology_note": "按官方资料复算。",
            "literature_review_markdown": long_text("文献综述", 500),
            "analysis_markdown": long_text("分析", 500),
            "answer_markdown": long_text("回答", 400),
            "conclusion_markdown": long_text("结论", 400),
            "limitations_markdown": "公开资料边界已列明。",
            "evidence_ref_uri_list": ["source_ref:official_1"],
        },
        "research_data_points": research_points,
        "evidence_ref_uri_list": ["source_ref:official_1"],
        "source_count": 1,
        "independent_source_count": 1,
    }
    reviews = []
    if include_reviews:
        reviews = [
            {
                "stage": stage,
                "review_round": index,
                "reviewer_role": f"{stage}_reviewer",
                "reviewer_id": f"independent-{stage}",
                "review_kind": "deterministic" if stage == "browser" else "independent",
                "verdict": "GREEN",
                "reconciliation_status": "resolved",
                "input_artifact_hash": HASH,
                "output_artifact_hash": HASH,
                "findings": [],
            }
            for index, stage in enumerate(("evidence", "science", "writing", "browser", "final"), start=1)
        ]
    return {
        "pack_schema_version": RUN_PACK_SCHEMA_VERSION,
        "workflow_contract_version": RESEARCH_WORKFLOW_CONTRACT_VERSION,
        "quality_profile": "standard",
        "slug": "workflow-v2-theory-fixture",
        "display_title": "理论研究指标复算",
        "research_question": "如何定义并复算一个理论研究指标？",
        "problem_statement": "验证理论实体不评分和可审计发布门禁。",
        "requested_by": "unit_test",
        "run_mode": "c_open",
        "as_of_date": "2026-07-12",
        "intake": {
            "research_question": "如何定义并复算一个理论研究指标？",
            "available_materials_choice": "A",
            "intake_material_type": "none",
            "evidence_policy": "accuracy_first",
            "time_window": {},
            "research_scope": {},
            "special_constraints": {},
            "field_origin": {"research_question": "user_provided"},
            "default_accepted": {},
        },
        "search_plan": [],
        "sources": [source],
        "claims": [],
        "data_points": [
            {
                "source_ref": "official_1",
                "entity_key": "theory_entity",
                "metric": f"平行数据点 {index}",
                "period": "2026",
                "value_num": float(index),
                "unit": "项",
                "source_excerpt": f"官方资料中的第 {index} 个可追溯观测对象。",
            }
            for index in range(1, 101)
        ],
        "entities": [entity],
        "entity_sections": [
            {
                "entity_key": "theory_entity",
                "section_key": "entity_answer",
                "section_title": "理论研究回答",
                "body_markdown": long_text("实体正文", 1900),
                "support_status": "supported",
                "evidence_ref_uri_list": ["source_ref:official_1"],
            }
        ],
        "entity_investment_targets": [],
        "sections": [
            {
                "section_key": "overview",
                "section_title": "研究总览",
                "body_markdown": long_text("总览正文", 1300),
                "support_status": "supported",
                "evidence_ref_uri_list": ["source_ref:official_1"],
            }
        ],
        "visuals": [],
        "early_signals": [],
        "supplement_requests": [],
        "audit_issues": [],
        "review_records": reviews,
    }


def build_market_pack() -> dict:
    pack = build_theory_pack()
    for index in range(2, 6):
        source = dict(pack["sources"][0])
        source.update({
            "ref": f"official_{index}",
            "title": f"官方研究资料 {index}",
            "title_zh": f"官方研究资料 {index}",
            "publisher": f"官方机构 {index}",
            "url": f"https://example.com/official-method-{index}",
            "independence_key": f"official_method_{index}_20260701",
            "independence_rationale": f"第 {index} 个官方机构独立发布的原始材料。",
        })
        pack["sources"].append(source)
    entity = pack["entities"][0]
    entity["entity_research_mode"] = "market_linked"
    entity.pop("research_profile", None)
    entity.pop("research_data_points", None)
    refs = [f"source_ref:official_{index}" for index in range(1, 6)]
    entity["evidence_ref_uri_list"] = refs
    entity.update({
        "score_point": 76.0,
        "score_band_low": 70.0,
        "score_band_high": 82.0,
        "coverage": 0.85,
        "confidence": 0.82,
        "factor_scores": [{
            "factor_code": "demand.downstream_price_momentum",
            "metric_name": "下游价格确认强度",
            "period": "2026",
            "unit": "分",
            "score_raw": 78.0,
            "score_adjusted": 76.0,
            "coverage": 0.90,
            "confidence": 0.85,
            "score_rationale": "五个独立官方来源均显示价格、订单或采购行为改善，但持续时间仍需后续季度数据确认，因此未给满分。",
            "factor_value_summary": "当前读数表明下游价格确认已从单一线索扩展为多来源交叉验证，强度较高但尚未覆盖完整周期。",
            "source_context_summary": "五个来源分别来自独立官方机构，口径均指向 2026 年价格与采购行为，未把转载重复计算。",
            "factor_topic_analysis": "价格确认提高了需求兑现概率，但若后续订单和现金流没有同步，当前高分应下调而不是继续外推。",
            "theme_analysis_points": [
                "价格、订单和采购行为同时改善，说明需求不再只停留在远期叙事。",
                "若下一季度价格回落且订单未兑现，应把该因子降为观察而非维持高分。",
            ],
            "evidence_ref_uri_list": refs,
            "information_points": [
                {
                    "evidence_ref": ref,
                    "excerpt": f"第 {index} 个官方来源确认价格或采购行为改善。",
                    "interpretation": f"第 {index} 个来源独立验证需求兑现，同时保留持续性尚未确认的限制。",
                }
                for index, ref in enumerate(refs, start=1)
            ],
        }],
    })
    pack["entity_investment_targets"] = [{
        "entity_key": "theory_entity",
        "target_name": "测试上市公司",
        "ticker": "TEST.US",
        "market": "美国",
        "target_type": "security",
        "target_url": "https://example.com/investor-relations",
        "exposure_rationale": "公司收入与本实体价格和订单变化直接相关。",
        "research_action": "跟踪订单兑现、毛利率和经营现金流是否同步改善。",
        "investment_view": "仅在价格确认转化为利润和现金流时提高研究优先级。",
        "risk_note": "价格信号可能来自短期补库，若终端需求转弱则利润弹性会反向。",
        "target_priority": "P1",
        "target_quality_label": "高置信度",
        "relative_preference": "在同实体标的中优先验证现金流兑现。",
        "confirmed_scenario_action": "订单、毛利和现金流连续两个季度改善后上调优先级。",
        "falsified_scenario_action": "价格回落且库存上升时下调为观察并停止高增长外推。",
        "target_profile_markdown": "测试公司直接暴露于价格和订单变化，业务边界及验证指标已经列明。",
        "target_deep_research_markdown": "研究重点是价格信号能否穿透到收入、毛利和经营现金流，而非只看主题相关性。",
        "entity_relation_markdown": "该公司是本实体需求兑现的直接承接者。",
        "parent_research_relation_markdown": "该标的用于检验主问题中的价格与利润传导。",
        "conditional_investment_recommendation": "证实利润和现金流同步后再提高配置研究优先级。",
        "financial_data_status": "财务字段已进入独立完整性复核。",
        "link_status": "linked",
        "support_status": "supported",
        "target_data_points": [{
            "metric_name": "订单兑现验证",
            "metric_category": "operations",
            "period": "2026Q2",
            "value_text": "订单与价格同步改善",
            "unit": "文本",
            "source_title": "官方研究资料",
            "source_publisher": "官方机构",
            "source_url": "https://example.com/official-method",
            "source_excerpt": "官方资料确认订单与价格同步改善。",
            "evidence_ref_uri": "source_ref:official_1",
            "data_quality_label": "verified",
            "direction": "positive",
        }],
    }]
    pack["sections"][0]["evidence_ref_uri_list"] = refs
    pack["entity_sections"][0]["evidence_ref_uri_list"] = refs
    for index, stage in enumerate(("calculation", "financial"), start=20):
        pack["review_records"].append({
            "stage": stage,
            "review_round": index,
            "reviewer_role": f"{stage}_reviewer",
            "reviewer_id": f"independent-{stage}",
            "review_kind": "independent",
            "verdict": "GREEN",
            "reconciliation_status": "resolved",
            "input_artifact_hash": HASH,
            "output_artifact_hash": HASH,
            "findings": [],
        })
    return pack


class WorkflowV2ContractTests(unittest.TestCase):
    def test_v2_pack_publish_contract(self):
        report = validate_run_pack(build_theory_pack(), publication_mode="publish")
        self.assertTrue(report.valid, report.as_dict())
        self.assertEqual(report.metrics["theory_research_entity_count"], 1)
        self.assertEqual(report.metrics["factor_count"], 0)

    def test_target_type_must_match_database_contract(self):
        pack = build_market_pack()
        pack["entity_investment_targets"][0]["target_type"] = "observation_basket"
        report = validate_run_pack(pack, publication_mode="stage")
        self.assertIn("target_type_invalid", {issue.code for issue in report.blockers})

    def test_v2_pack_requires_independent_display_title(self):
        pack = build_theory_pack()
        pack.pop("display_title")
        report = validate_run_pack(pack, publication_mode="stage")
        self.assertIn(
            ("missing_field", "display_title"),
            {(issue.code, issue.path) for issue in report.blockers},
        )

    def test_market_pack_requires_and_accepts_adaptive_reviews(self):
        pack = build_market_pack()
        report = validate_run_pack(pack, publication_mode="publish")
        self.assertTrue(report.valid, report.as_dict())
        self.assertEqual(report.metrics["market_linked_entity_count"], 1)
        missing_calculation = build_market_pack()
        missing_calculation["review_records"] = [
            item for item in missing_calculation["review_records"] if item["stage"] != "calculation"
        ]
        failed = validate_run_pack(missing_calculation, publication_mode="publish")
        self.assertIn("review_records_missing", {issue.code for issue in failed.blockers})

    def test_static_review_contract_does_not_satisfy_publication(self):
        pack = build_theory_pack(include_reviews=False)
        pack["workflow_review_contract"] = {"reviewer_roles": ["evidence", "science", "writing", "final"]}
        report = validate_run_pack(pack, publication_mode="publish")
        self.assertFalse(report.valid)
        self.assertIn("review_records_missing", {issue.code for issue in report.blockers})

    def test_v2_contract_rejects_split_series_missing_translation_and_incomplete_review(self):
        pack = build_theory_pack()
        split = dict(pack["data_points"][0])
        split["period"] = "2027"
        split["value_num"] = 999.0
        pack["data_points"].append(split)
        pack["sources"][0]["language"] = "en"
        pack["sources"][0].pop("title_zh", None)
        pack["sources"][0].pop("excerpt_zh", None)
        pack["review_records"][0].pop("output_artifact_hash", None)
        report = validate_run_pack(pack, publication_mode="publish")
        codes = {issue.code for issue in report.blockers}
        self.assertIn("data_identity_duplicate", codes)
        self.assertIn("source_translation_missing", codes)
        self.assertIn("review_record_field", codes)

    def test_v2_contract_rejects_machine_evidence_refs_and_malformed_review_hash(self):
        pack = build_theory_pack()
        pack["entities"][0]["evidence_ref_uri_list"] = ["opp://source/1"]
        pack["review_records"][0]["input_artifact_hash"] = "sha256:not-a-real-hash"
        report = validate_run_pack(pack, publication_mode="publish")
        codes = {issue.code for issue in report.blockers}
        self.assertIn("evidence_ref_format", codes)
        self.assertIn("review_artifact_hash", codes)

    def test_v2_contract_rejects_machine_labels_in_human_fields(self):
        pack = build_theory_pack()
        pack["data_points"][0]["metric"] = "time_series_data_point"
        pack["sources"][0]["title"] = "这是 Opportunity Lens 来源记录。"
        report = validate_run_pack(pack, publication_mode="stage")
        self.assertIn("machine_label", {issue.code for issue in report.blockers})

    def test_v2_contract_rejects_supplement_enum_before_database_write(self):
        pack = build_theory_pack()
        pack["supplement_requests"] = [
            {
                "entity_key": "theory_entity",
                "request_title": "补充验证",
                "request_detail": "取得新的官方原始证据。",
                "priority": "p1",
                "blocking_status": "limits_precision",
                "review_status": "pending",
                "evidence_ref_uri": "source_ref:official_1",
            }
        ]
        report = validate_run_pack(pack, publication_mode="stage")
        self.assertFalse(report.valid)
        self.assertTrue(
            any(
                issue.code == "enum_value"
                and issue.path
                == "supplement_requests[0].blocking_status"
                for issue in report.blockers
            )
        )

    def test_market_entity_requires_scores_and_target(self):
        pack = build_theory_pack()
        entity = pack["entities"][0]
        entity["entity_research_mode"] = "market_linked"
        entity.pop("factor_scores", None)
        report = validate_run_pack(pack, publication_mode="stage")
        codes = {issue.code for issue in report.blockers}
        self.assertIn("market_scores_missing", codes)
        self.assertIn("market_target_missing", codes)

    def test_bundled_time_series_is_one_data_point_and_loader_preserves_observations(self):
        pack = build_theory_pack()
        point = pack["data_points"][0]
        point.pop("value_num", None)
        point.pop("period", None)
        point["observations"] = [
            {"period": "2025", "value_num": 10.0},
            {"period": "2026", "value_num": 12.0},
        ]
        self.assertTrue(validate_run_pack(pack, publication_mode="stage").valid)
        with tempfile.TemporaryDirectory() as tmp:
            pack_path = Path(tmp) / "pack.json"
            db_path = Path(tmp) / "opportunity_lens.db"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            run_id = load_pack(pack_path, db_path=db_path, publication_mode="stage")
            conn = connect(db_path)
            try:
                row = conn.execute(
                    "SELECT value_num,value_text FROM opportunity_data_point WHERE run_id=? AND metric=?",
                    (run_id, point["metric"]),
                ).fetchone()
                payload = json.loads(row["value_text"])
                self.assertIsNone(row["value_num"])
                self.assertEqual(payload["kind"], "time_series_data_point")
                self.assertEqual(payload["observation_count"], 2)
            finally:
                conn.close()

    def test_loader_never_promotes_weak_source_to_core_evidence(self):
        pack = build_theory_pack()
        weak_source = dict(pack["sources"][0])
        weak_source.update(
            {
                "ref": "weak_context_1",
                "title": "仅供压力情景参考的媒体估计",
                "title_zh": "仅供压力情景参考的媒体估计",
                "publisher": "媒体",
                "url": "https://example.com/weak-context",
                "source_tier": "C",
                "source_review_status": "weak_source_only",
                "independence_key": "weak_context_20260701",
                "independence_rationale": "匿名市场估计，只能用于参考情景。",
            }
        )
        pack["sources"].append(weak_source)

        with tempfile.TemporaryDirectory() as tmp:
            pack_path = Path(tmp) / "pack.json"
            db_path = Path(tmp) / "opportunity_lens.db"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            run_id = load_pack(pack_path, db_path=db_path, publication_mode="stage")
            conn = connect(db_path)
            try:
                row = conn.execute(
                    """
                    SELECT policy_evidence_role,policy_gate_verdict,scoring_eligibility
                    FROM opportunity_source
                    WHERE run_id=? AND title=?
                    """,
                    (run_id, weak_source["title"]),
                ).fetchone()
                self.assertEqual(row["policy_evidence_role"], "reference_only")
                self.assertEqual(row["policy_gate_verdict"], "pass_reference")
                self.assertEqual(row["scoring_eligibility"], "reference_only")
            finally:
                conn.close()

    def test_loader_factor_gate_uses_only_factor_refs_and_independence_groups(self):
        pack = build_market_pack()
        extra = dict(pack["sources"][0])
        extra.update(
            {
                "ref": "official_6",
                "title": "第六个因子官方资料",
                "title_zh": "第六个因子官方资料",
                "publisher": "官方机构 6",
                "url": "https://example.com/factor-official-6",
                "independence_key": "official_method_6_20260701",
                "independence_rationale": "第六个独立官方机构发布的原始材料。",
            }
        )
        pack["sources"].append(extra)
        context_only = dict(extra)
        context_only.update(
            {
                "ref": "official_7",
                "title": "仅供实体背景使用的官方资料",
                "title_zh": "仅供实体背景使用的官方资料",
                "publisher": "官方机构 7",
                "url": "https://example.com/entity-context-only",
                "independence_key": "entity_context_only_20260701",
                "independence_rationale": "该来源只绑定实体背景，不属于本因子的证据。",
            }
        )
        pack["sources"].append(context_only)
        factor = pack["entities"][0]["factor_scores"][0]
        factor["evidence_ref_uri_list"] = [
            *factor["evidence_ref_uri_list"],
            "source_ref:official_6",
        ]
        pack["entities"][0]["evidence_ref_uri_list"] = [
            *pack["entities"][0]["evidence_ref_uri_list"],
            "source_ref:official_6",
            "source_ref:official_7",
        ]
        # official_1 与 official_2 是同一底层发布的两个事实簇，URI 不同但只计一组。
        pack["sources"][1]["independence_key"] = pack["sources"][0]["independence_key"]
        pack["sources"][1]["independence_rationale"] = "与 official_1 来自同一底层发布。"

        with tempfile.TemporaryDirectory() as tmp:
            pack_path = Path(tmp) / "pack.json"
            db_path = Path(tmp) / "opportunity_lens.db"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            run_id = load_pack(pack_path, db_path=db_path, publication_mode="stage")
            conn = connect(db_path)
            try:
                row = conn.execute(
                    "SELECT factor_trace_json FROM opportunity_factor_score WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                trace = json.loads(row["factor_trace_json"])
                self.assertEqual(len(trace["evidence_refs"]), 6)
                self.assertFalse(any(ref.endswith("/7") for ref in trace["evidence_refs"]))
                weighting = trace["evidence_weighting"]
                self.assertEqual(weighting["available_group_count"], 5)
                self.assertEqual(len(weighting["items"]), 5)
                self.assertEqual(
                    len({item["independence_key"] for item in weighting["items"]}),
                    5,
                )
            finally:
                conn.close()

    def test_loader_persists_explicit_metric_slots_and_data_point_links(self):
        pack = build_market_pack()
        pack["data_points"][0]["data_point_key"] = "price_primary"
        pack["data_points"][1]["data_point_key"] = "price_support"
        pack["data_points"][1]["source_ref"] = "official_2"
        factor = pack["entities"][0]["factor_scores"][0]
        factor.update({
            "score_raw": 75.0,
            "score_adjusted": 72.5,
            "coverage": 1.0,
            "confidence": 0.80,
            "coverage_multiplier": 1.0,
            "confidence_multiplier": 0.90,
            "audit_multiplier": 1.0,
            "reliability_multiplier": 0.90,
            "metric_slots": [
                {
                    "slot_code": "downstream_price_3m_change",
                    "slot_label": "三个月价格变化",
                    "metric_name": "下游产品三个月价格变化",
                    "slot_role": "primary",
                    "slot_weight": 0.6,
                    "slot_score": 78.0,
                    "slot_confidence": 0.88,
                    "value_status": "calculated",
                    "unit": "%",
                    "period": "2026Q2",
                    "source_refs": ["official_1"],
                    "data_point_keys": ["price_primary"],
                    "raw_value_text": "官方月度价格序列",
                    "raw_unit": "%",
                    "standardized_value_text": "三个月价格上涨",
                    "standardized_unit": "%",
                    "normalization_method": "将同品类月度价格序列换算为三个月百分比变化",
                    "bucket": "明显上涨",
                    "scoring_rule": "三个月价格涨幅位于+5%至+15%计70分，本样本按插值固定为78分",
                    "preprocess_trace": "按同口径月份复算三个月变化。",
                    "scoring_trace": "按冻结价格分档得到78分。",
                },
                {
                    "slot_code": "downstream_price_yoy_change",
                    "slot_label": "同比价格变化",
                    "metric_name": "下游产品同比价格变化",
                    "slot_role": "supporting",
                    "slot_weight": 0.4,
                    "slot_score": 70.0,
                    "slot_confidence": 0.72,
                    "value_status": "available",
                    "unit": "%",
                    "period": "2026Q2",
                    "source_refs": ["official_2"],
                    "data_point_keys": ["price_support"],
                    "raw_value_text": "官方同比观测",
                    "raw_unit": "%",
                    "standardized_value_text": "同比改善",
                    "standardized_unit": "%",
                    "normalization_method": "按同品类、同期基准计算同比变化",
                    "bucket": "温和上涨",
                    "scoring_rule": "同比改善按冻结辅助信号分档计70分",
                    "preprocess_trace": "按同期口径对齐。",
                    "scoring_trace": "按冻结价格分档得到70分。",
                },
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            pack_path = Path(tmp) / "pack.json"
            db_path = Path(tmp) / "opportunity_lens.db"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            run_id = load_pack(pack_path, db_path=db_path, publication_mode="stage")
            conn = connect(db_path)
            try:
                slots = conn.execute(
                    "SELECT * FROM opportunity_metric_slot WHERE run_id=? ORDER BY id",
                    (run_id,),
                ).fetchall()
                self.assertEqual(len(slots), 2)
                self.assertEqual(slots[0]["slot_key"], "downstream_price_3m_change")
                self.assertIsNotNone(slots[0]["selected_data_point_id"])
                self.assertIn("标准化结果：三个月价格上涨", slots[0]["notes"])
                links = conn.execute(
                    "SELECT * FROM opportunity_slot_data_point_link WHERE slot_id IN (?,?)",
                    (slots[0]["id"], slots[1]["id"]),
                ).fetchall()
                self.assertEqual(len(links), 2)
                score = conn.execute(
                    "SELECT * FROM opportunity_factor_score WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                self.assertAlmostEqual(score["coverage_multiplier"], 1.0)
                self.assertAlmostEqual(score["reliability_multiplier"], 0.90)
            finally:
                conn.close()

    def test_validate_only_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.json"
            path.write_text(json.dumps(build_theory_pack(), ensure_ascii=False), encoding="utf-8")
            report = validate_pack_file(path, publication_mode="validate")
            self.assertTrue(report["valid"])
            self.assertGreaterEqual(report["metrics"]["workflow_brief_requirement_count"], 2)
            self.assertTrue(report["metrics"]["workflow_brief_hash"].startswith("sha256:"))
            self.assertEqual(report["public_content_quality_audit"]["status"], "PASS")
            self.assertTrue(report["metrics"]["public_content_audit_result_sha256"].startswith("sha256:"))
            self.assertFalse((Path(tmp) / "opportunity_lens.db").exists())

    def test_historical_v2_pack_without_modeling_marker_remains_compatible(self):
        pack = build_theory_pack()
        self.assertNotIn("modeling_contract_version", pack)
        report = validate_run_pack(pack, publication_mode="validate")
        self.assertTrue(report.valid, report.as_dict())

    def test_new_modeling_contract_rejects_completed_record_without_artifact_hashes(self):
        pack = build_theory_pack()
        pack.update({
            "modeling_contract_version": "research.modeling_skills.v1",
            "modeling_records": [{
                "skill_name": "company_financial_modeling",
                "status": "completed",
                "input_artifact_hash": "not-a-hash",
                "output_artifact_hash": HASH,
            }],
            "independent_model_freezes": [],
            "external_reconciliations": [],
        })
        report = validate_run_pack(pack, publication_mode="validate")
        self.assertFalse(report.valid)
        self.assertIn("modeling_contract", {issue.code for issue in report.issues})

    def test_new_financial_pack_cannot_publish_before_skills_freeze_and_reconciliation(self):
        pack = build_theory_pack()
        pack["display_title"] = "测试公司估值"
        pack["research_question"] = "估值某上市公司的合理价值"
        pack["intake"]["research_question"] = pack["research_question"]
        pack.update({
            "modeling_contract_version": "research.modeling_skills.v1",
            "modeling_records": [],
            "independent_model_freezes": [],
            "external_reconciliations": [],
        })
        with self.assertRaisesRegex(ValueError, "required_modeling_skill_not_completed"):
            build_pack_workflow_state(pack, pack_hash=HASH, publication_mode="publish")

        pack["modeling_records"] = [
            {
                "skill_name": skill_name,
                "status": "completed",
                "input_artifact_hash": HASH,
                "output_artifact_hash": HASH,
                "note": "独立模型已完成并冻结。",
            }
            for skill_name in ("company_financial_modeling", "company_valuation_modeling")
        ]
        pack["independent_model_freezes"] = [{
            "model_ref": "financial:test-company:FY1-FY3",
            "input_hash": HASH,
            "output_hash": HASH,
            "frozen_before_consensus": True,
        }]
        pack["external_reconciliations"] = [{
            "model_ref": "financial:test-company:FY1-FY3",
            "benchmark_ref": "wind-consensus:2026-07-22",
            "artifact_hash": HASH,
            "status": "completed_with_gap",
        }]
        _brief, manifest = build_pack_workflow_state(
            pack, pack_hash=HASH, publication_mode="publish",
        )
        self.assertEqual(manifest.publication["status"], "eligible")

    def test_optional_prompt_requirement_matrix_is_preserved_in_shared_brief(self):
        pack = build_theory_pack(include_reviews=False)
        pack["prompt_requirements"] = [
            {
                "question": "分别核验产品、客户资格和重复订单。",
                "output_hint": "run_overview",
                "acceptance_criteria": "公开正文必须分别给出证据和结论。",
            },
            {
                "question": "建立独立财务模型并解释与市场预期的差异。",
                "output_hint": "run_overview",
                "acceptance_criteria": "先冻结独立结果，再执行外部对账。",
            },
        ]
        brief, _manifest = build_pack_workflow_state(
            pack, pack_hash=HASH, publication_mode="stage",
        )
        questions = [item.question for item in brief.requirements]
        self.assertIn("分别核验产品、客户资格和重复订单。", questions)
        self.assertIn("建立独立财务模型并解释与市场预期的差异。", questions)
        self.assertEqual(len(brief.requirements), 4)

    def test_bad_public_content_cannot_validate_or_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_theory_pack()
            pack["sections"][0]["body_markdown"] += (
                "\n\n字段完成情况由 canonical intake 和参数 owner 决定。"
            )
            pack_path = root / "bad-pack.json"
            db_path = root / "opportunity_lens.db"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            report = validate_pack_file(pack_path, publication_mode="validate")
            self.assertFalse(report["valid"])
            self.assertIn(
                "public_content_quality_audit",
                {issue["code"] for issue in report["issues"]},
            )
            with self.assertRaisesRegex(ValueError, "公开内容门禁失败"):
                load_pack(pack_path, db_path=db_path, publication_mode="stage")
            self.assertFalse(db_path.exists())

    def test_public_content_change_invalidates_embedded_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_theory_pack()
            pack[PUBLIC_AUDIT_FIELD] = build_pack_audit_attestation(pack, profile="auto")
            pack["sections"][0]["body_markdown"] += (
                "\n\n补充段落继续解释官方证据、估算方法和当前结论。"
            )
            pack_path = root / "stale-pack.json"
            db_path = root / "opportunity_lens.db"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            report = validate_pack_file(pack_path, publication_mode="validate")
            self.assertFalse(report["valid"])
            self.assertIn(
                "public_content_audit_stale",
                {issue["code"] for issue in report["issues"]},
            )
            with self.assertRaisesRegex(ValueError, "已失效"):
                load_pack(pack_path, db_path=db_path, publication_mode="stage")
            self.assertFalse(db_path.exists())

    def test_replace_refreshes_public_content_audit_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack_path = root / "pack.json"
            db_path = root / "opportunity_lens.db"
            first_pack = build_theory_pack(include_reviews=False)
            pack_path.write_text(json.dumps(first_pack, ensure_ascii=False), encoding="utf-8")
            run_id = load_pack(pack_path, db_path=db_path, publication_mode="stage")
            conn = connect(db_path)
            try:
                first_hash = conn.execute(
                    "SELECT manifest_hash FROM opportunity_run_manifest "
                    "WHERE run_id=? AND manifest_type='public_content_quality_audit'",
                    (run_id,),
                ).fetchone()[0]
            finally:
                conn.close()

            second_pack = build_theory_pack(include_reviews=False)
            second_pack["sections"][0]["body_markdown"] += (
                "\n\n新增证据说明复算输入没有改变核心判断；目前只有一个独立来源，因此结论置信度保持中等。"
            )
            pack_path.write_text(json.dumps(second_pack, ensure_ascii=False), encoding="utf-8")
            replaced_id = load_pack(
                pack_path,
                db_path=db_path,
                publication_mode="stage",
                replace=True,
            )
            self.assertEqual(replaced_id, run_id)
            conn = connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT manifest_hash,manifest_json FROM opportunity_run_manifest "
                    "WHERE run_id=? AND manifest_type='public_content_quality_audit'",
                    (run_id,),
                ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertNotEqual(rows[0]["manifest_hash"], first_hash)
                self.assertEqual(json.loads(rows[0]["manifest_json"])["status"], "PASS")
            finally:
                conn.close()

    def test_legacy_pack_retains_compatibility_without_v2_public_audit_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = build_theory_pack(include_reviews=False)
            pack.pop("pack_schema_version", None)
            pack.pop("workflow_contract_version", None)
            pack_path = root / "legacy-pack.json"
            db_path = root / "opportunity_lens.db"
            pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            run_id = load_pack(pack_path, db_path=db_path, publication_mode="stage")
            conn = connect(db_path)
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM opportunity_run_manifest "
                        "WHERE run_id=? AND manifest_type='public_content_quality_audit'",
                        (run_id,),
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()

    def test_loader_stages_by_default_and_direct_publish_requires_staged_browser_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack_path = root / "pack.json"
            pack_path.write_text(json.dumps(build_theory_pack(), ensure_ascii=False), encoding="utf-8")

            staged_db = root / "staged" / "opportunity_lens.db"
            run_id = load_pack(pack_path, db_path=staged_db, publication_mode="stage")
            conn = connect(staged_db)
            try:
                run = conn.execute(
                    "SELECT display_title,run_status,run_readiness_status FROM opportunity_run WHERE id=?",
                    (run_id,),
                ).fetchone()
                self.assertEqual(run["display_title"], "理论研究指标复算")
                self.assertEqual((run["run_status"], run["run_readiness_status"]), ("under_review", "reviewable"))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_quality_gate_result WHERE run_id=?", (run_id,)).fetchone()[0], 5)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_agent_review_log WHERE run_id=?", (run_id,)).fetchone()[0], 5)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_factor_score WHERE run_id=?", (run_id,)).fetchone()[0], 0)
                source = conn.execute(
                    "SELECT event_date,fetch_date,local_locator FROM opportunity_source WHERE run_id=? ORDER BY id LIMIT 1",
                    (run_id,),
                ).fetchone()
                self.assertEqual(source["event_date"], "2026-06-30")
                self.assertEqual(source["fetch_date"], "2026-07-12")
                self.assertEqual(source["local_locator"], "原文P3，方法表第一行")
                workflow_rows = conn.execute(
                    "SELECT manifest_type,manifest_json FROM opportunity_run_manifest WHERE run_id=? AND manifest_type IN ('research_brief','research_execution_manifest')",
                    (run_id,),
                ).fetchall()
                self.assertEqual({row["manifest_type"] for row in workflow_rows}, {"research_brief", "research_execution_manifest"})
                payloads = {row["manifest_type"]: json.loads(row["manifest_json"]) for row in workflow_rows}
                self.assertGreaterEqual(len(payloads["research_brief"]["requirements"]), 2)
                execution = payloads["research_execution_manifest"]
                self.assertEqual(
                    {gate["gate"] for gate in execution["gates"]},
                    {"contract", "evidence_integrity", "provenance", "duplication", "scope_and_units"},
                )
                self.assertTrue(all(item["status"] == "completed" for item in execution["requirement_coverage"].values()))
                manual_manifest = conn.execute(
                    "SELECT manifest_json FROM opportunity_run_manifest WHERE run_id=? AND manifest_type='manual_research_pack'",
                    (run_id,),
                ).fetchone()
                cache_record = json.loads(manual_manifest["manifest_json"])["content_cache"]
                self.assertTrue(cache_record["hash"].startswith("sha256:"))
                self.assertTrue(Path(cache_record["path"]).is_file())
                public_audit_row = conn.execute(
                    "SELECT manifest_json,manifest_hash FROM opportunity_run_manifest "
                    "WHERE run_id=? AND manifest_type='public_content_quality_audit'",
                    (run_id,),
                ).fetchone()
                self.assertIsNotNone(public_audit_row)
                public_audit = json.loads(public_audit_row["manifest_json"])
                self.assertEqual(public_audit["status"], "PASS")
                self.assertTrue(public_audit["rules_sha256"].startswith("sha256:"))
                self.assertTrue(public_audit["pack_sha256"].startswith("sha256:"))
                self.assertEqual(public_audit_row["manifest_hash"], public_audit["result_sha256"])
            finally:
                conn.close()

            with self.assertRaises(ValueError):
                load_pack(pack_path, db_path=staged_db, publication_mode="stage")
            replaced_id = load_pack(
                pack_path,
                db_path=staged_db,
                publication_mode="stage",
                replace=True,
            )
            self.assertEqual(replaced_id, run_id)

            published_db = root / "published" / "opportunity_lens.db"
            with self.assertRaisesRegex(ValueError, "browser_visual_audit manifest"):
                load_pack(pack_path, db_path=published_db, publication_mode="publish")
            conn = connect(published_db)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_run").fetchone()[0], 0)
            finally:
                conn.close()

    def test_stage_mode_does_not_fabricate_missing_reviewer_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack_path = root / "pack.json"
            db_path = root / "opportunity_lens.db"
            pack_path.write_text(
                json.dumps(build_theory_pack(include_reviews=False), ensure_ascii=False),
                encoding="utf-8",
            )
            run_id = load_pack(pack_path, db_path=db_path, publication_mode="stage")
            conn = connect(db_path)
            try:
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM opportunity_agent_review_log WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0], 0)
                row = conn.execute(
                    "SELECT manifest_json FROM opportunity_run_manifest WHERE run_id=? AND manifest_type='research_execution_manifest'",
                    (run_id,),
                ).fetchone()
                shared = json.loads(row["manifest_json"])
                self.assertEqual(shared["reviews"], [])
                self.assertEqual(shared["publication"]["status"], "staged")
                self.assertIn("final", shared["required_reviews"])
            finally:
                conn.close()

    def test_publication_rejects_tampered_gate_and_review_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack_path = root / "pack.json"
            db_path = root / "opportunity_lens.db"
            pack_path.write_text(json.dumps(build_theory_pack(), ensure_ascii=False), encoding="utf-8")
            run_id = load_pack(pack_path, db_path=db_path, publication_mode="stage")
            conn = connect(db_path)
            try:
                conn.execute(
                    "UPDATE opportunity_quality_gate_result SET result_hash='sha256:tampered' WHERE run_id=? AND gate_name='contract'",
                    (run_id,),
                )
                conn.execute(
                    "UPDATE opportunity_agent_review_log SET findings_json='[{\"tampered\":true}]' WHERE run_id=? AND review_stage='evidence'",
                    (run_id,),
                )
                report = evaluate_publication_gate(conn, run_id)
                self.assertFalse(report.eligible)
                self.assertTrue(any("门禁记录 hash 校验失败" in item for item in report.blockers))
                self.assertTrue(any("reviewer findings hash 校验失败" in item for item in report.blockers))
            finally:
                conn.close()


class TheoryScoringExclusionTests(FixtureDBTestCase):
    def test_generic_scoring_excludes_theory_entity(self):
        conn = connect(self.db_path)
        try:
            entity_id = conn.execute("SELECT entity_id FROM opportunity_entity_maturation WHERE run_id=? ORDER BY entity_id LIMIT 1", (self.run_id,)).fetchone()[0]
            conn.execute(
                """
                INSERT INTO opportunity_entity_research_profile(
                  run_id,entity_id,entity_research_mode,research_depth_status,research_question,
                  literature_review_markdown,analysis_markdown,answer_markdown,conclusion_markdown
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id,entity_id) DO UPDATE SET entity_research_mode='theory_research'
                """,
                (self.run_id, entity_id, "theory_research", "complete", "q", "l", "a", "answer", "c"),
            )
            batch_id = create_score_batch(conn, self.run_id)
            count = conn.execute(
                "SELECT COUNT(*) FROM opportunity_factor_score WHERE score_batch_id=? AND entity_id=?",
                (batch_id, entity_id),
            ).fetchone()[0]
            maturity = conn.execute(
                "SELECT maturation_status FROM opportunity_entity_maturation WHERE run_id=? AND entity_id=?",
                (self.run_id, entity_id),
            ).fetchone()[0]
            self.assertEqual(count, 0)
            self.assertEqual(maturity, "research_only")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
