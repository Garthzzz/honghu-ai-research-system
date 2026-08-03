from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from tools.opportunity_lens.build_silicon_wafer_demand_run_pack import (
    FACTOR_ROUTES,
    build_pack as build_demand_pack,
)
from tools.opportunity_lens.build_silicon_wafer_equipment_run_pack import (
    build_pack as build_equipment_pack,
)
from tools.opportunity_lens.run_pack_contract import validate_run_pack
from tools.opportunity_lens.silicon_run_pack_support import SEGMENT_FACTOR_CODES


def _assert_pack_core(pack: dict, *, minimum_points: int, entity_count: int) -> None:
    assert pack["pack_schema_version"] == "opportunity_lens.run_pack.v2"
    assert len(pack["data_points"]) >= minimum_points
    assert len(pack["entities"]) == entity_count
    assert len(pack["entity_sections"]) == entity_count
    for entity in pack["entities"]:
        assert tuple(item["factor_code"] for item in entity["factor_scores"]) == SEGMENT_FACTOR_CODES
        assert all(len(item["information_points"]) >= 5 for item in entity["factor_scores"])
    report = validate_run_pack(pack, publication_mode="stage")
    assert report.valid, report.as_dict()


def test_equipment_pack_builds_with_complete_segments() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output_dir = Path(directory)
        pack = build_equipment_pack(output_dir=output_dir)
        model = json.loads(
            (output_dir / "model_outputs.json").read_text(encoding="utf-8")
        )
    _assert_pack_core(pack, minimum_points=100, entity_count=5)
    assert len(pack["entity_investment_targets"]) == 7
    assert len(pack["data_points"]) == 154
    assert pack["evidence_audit"]["data_points"]["drop_count"] == 1
    assert pack["evidence_audit"]["sources"]["updated_count"] == 1
    assert pack["model_artifacts"]["model_inputs_sha256"].startswith("sha256:")
    assert pack["model_artifacts"]["model_outputs_sha256"].startswith("sha256:")
    assert pack["model_artifacts"]["evidence_audit_sha256"].startswith("sha256:")
    assert pack["model_artifacts"]["financial_evidence_audit_sha256"].startswith(
        "sha256:"
    )
    assert pack["model_artifacts"]["financial_targets_input_sha256"].startswith(
        "sha256:"
    )
    assert pack["model_artifacts"]["financial_sources_input_sha256"].startswith(
        "sha256:"
    )
    assert pack["financial_evidence_audit"]["audited_target_count"] == 7
    assert pack["financial_evidence_audit"]["financial_history_point_count"] == 22
    visual_keys = [visual["block_key"] for visual in pack["visuals"]]
    assert len(visual_keys) == len(set(visual_keys))
    assert {
        "equipment_market_space_results",
        "demand_wafer_process_supplier_chain",
        "wafer_maker_equipment_project_database",
        "silicon_wafer_equipment_chain_map",
        "soi_proprietary_process_chain",
        "wafer_maker_equipment_supplier_relationships",
        "named_supplier_inclusion_observation_exclusion",
        "listed_equipment_company_evidence_ranking",
        "listed_equipment_company_financial_snapshot",
    } <= set(visual_keys)
    source_by_ref = {source["ref"]: source for source in pack["sources"]}
    assert "Okmetic" in source_by_ref["S029"]["excerpt_zh"]
    relationship_rows = next(
        visual for visual in pack["visuals"]
        if visual["block_key"] == "wafer_maker_equipment_supplier_relationships"
    )["display_data"]["rows"]
    assert any(row[0] == "芬兰Okmetic" and row[2] == "晶盛机电" for row in relationship_rows)
    # 证据不足的实体可以共享50分的内部中性占位值；不能为了让向量“看起来不同”
    # 而伪造差异。公开层由score_status/score_grade把它们显示为未评级。
    evidence_poor = [
        entity
        for entity in pack["entities"]
        if all(
            factor["score_status"] == "insufficient_evidence"
            for factor in entity["factor_scores"]
        )
    ]
    assert {entity["key"] for entity in evidence_poor} == {
        "semiconductor_crystal_growth_tools",
        "wafer_final_clean_automation",
    }
    assert all(entity["score_status"] == "insufficient_evidence" for entity in evidence_poor)
    assert all(entity["score_grade"] == "unrated" for entity in evidence_poor)
    assert all(
        factor["score_adjusted"] == 50.0
        for entity in evidence_poor
        for factor in entity["factor_scores"]
    )
    for entity in pack["entities"]:
        ref_sets = {
            tuple(factor["evidence_ref_uri_list"])
            for factor in entity["factor_scores"]
        }
        assert len(ref_sets) >= 5
    identified_range = model["equipment_scenario_analysis"]["current_quantifiable_four_project_scenario_rmb_100m"]
    assert identified_range["low"] < identified_range["high"]
    assert identified_range["low"] == pytest.approx(
        model["identified_market"]["base_project_rmb_100m"]["low"], abs=0.0001
    )
    assert identified_range["high"] == pytest.approx(146.4038096065)
    assert "annual_totals_rmb_100m" not in model["equipment_scenario_analysis"]
    targets_by_name = {
        target["target_name"]: target for target in pack["entity_investment_targets"]
    }
    assert pack["financial_evidence_audit"]["current_valuation_point_count"] == 7
    traceability = pack["source_traceability_audit"]
    assert traceability["status"] == "pass"
    assert traceability["all_sources"]["source_ref_count"] == 105
    assert traceability["all_sources"]["generic_locator_count"] == 0
    assert traceability["public_body_and_targets"]["generic_locator_count"] == 0
    assert traceability["core_tables"]["generic_locator_count"] == 0
    assert traceability["model_inputs"]["generic_locator_count"] == 0
    assert traceability["usable_metric_slots"]["generic_locator_count"] == 0
    assert traceability["downgraded_due_to_traceability_count"] == 0
    assert traceability["direct_original_excerpt_count"] == 105
    assert traceability["summary_rewrite_count"] == 0
    assert traceability["EQ-EVID-005"] == "closed"
    direct_excerpt_audit = pack["source_direct_excerpt_audit"]
    assert direct_excerpt_audit["status"] == "pass"
    assert direct_excerpt_audit["source_count"] == 105
    assert direct_excerpt_audit["direct_original_excerpt_count"] == 105
    assert direct_excerpt_audit["summary_rewrite_count"] == 0
    assert direct_excerpt_audit["EQ-EVID-005"] == "closed"
    assert {row["ref"] for row in direct_excerpt_audit["records"]} == set(source_by_ref)
    assert source_by_ref["S065"]["publisher"] == "SEMI Silicon Manufacturers Group"
    history_series = [
        point
        for point in pack["data_points"]
        if point["source_ref"] == "S065"
    ]
    assert len(history_series) == 2
    assert {
        point["metric"]: [row["value_num"] for row in point["observations"]]
        for point in history_series
    } == {
        "出货面积": [12407, 14165, 14713, 12602, 12266],
        "销售额": [11.2, 12.6, 13.8, 12.3, 11.5],
    }
    report_text = "\n".join(section["body_markdown"] for section in pack["sections"])
    assert "2020年以来的硅片周期、本土扩产与设备国产化" in report_text
    assert "2026—2030年与2020—2022年最大的区别" in report_text
    data_points_by_source: dict[str, list[dict]] = {}
    for point in pack["data_points"]:
        data_points_by_source.setdefault(point["source_ref"], []).append(point)
    for row in direct_excerpt_audit["records"]:
        if row["origin_kind"] != "audited_data_point_exact":
            continue
        assert source_by_ref[row["ref"]]["excerpt"] in {
            point["source_excerpt"]
            for point in data_points_by_source[row["ref"]]
        }
    for local_ref in ("S001", "S003", "S004", "S005", "S006"):
        local_source = source_by_ref[local_ref]
        assert not local_source.get("url")
        assert local_source.get("local_path")
        assert (Path(__file__).resolve().parents[2] / local_source["local_path"]).is_file()
        assert local_source.get("local_locator")
    assert source_by_ref["FIN-EQ-HUHAI-DIVIDEND"]["publisher"] == "华海清科／上海证券交易所"
    assert all(
        any(
            point.get("metric_category") == "current_valuation_and_profitability"
            for point in target["target_data_points"]
        )
        for target in targets_by_name.values()
    )
    pva = targets_by_name["PVA TePla"]
    assert pva["ticker"] == "TPE.DE"
    assert pva["evidence_ref_uri"] == "source_ref:FIN-PVA-02"
    kla_2023 = next(
        point
        for point in targets_by_name["KLA"]["target_data_points"]
        if point.get("metric_category") == "financial_history"
        and point["period"] == "FY2023"
    )
    assert "3,387.28" in kla_2023["value_text"]
    jingsheng_2023 = next(
        point
        for point in targets_by_name["晶盛机电"]["target_data_points"]
        if point.get("metric_category") == "financial_history"
        and point["period"] == "FY2023"
    )
    assert "41.63%" in jingsheng_2023["value_text"]
    assert "2,474.74" in jingsheng_2023["value_text"]
    accretech_2025 = next(
        point
        for point in targets_by_name["东京精密／ACCRETECH"]["target_data_points"]
        if point.get("metric_category") == "financial_history"
        and point["period"] == "FY2025/03"
    )
    assert "62,453.00" in accretech_2025["value_text"]
    assert "41.49%" in accretech_2025["value_text"]

    factor_audit = pack["factor_public_content_audit"]
    assert factor_audit["status"] == "pass"
    assert factor_audit["factor_count"] == 50
    assert factor_audit["source_role_failure_count"] == 0
    assert factor_audit["duplicate_failure_count"] == 0
    assert factor_audit["unrated_factor_count"] == 45
    assert factor_audit["unrated_public_score_leak_count"] == 0
    assert factor_audit["rated_factor_count"] == 5
    assert factor_audit["rated_score_reconciliation_failure_count"] == 0
    for entity in pack["entities"]:
        for factor in entity["factor_scores"]:
            if factor["score_status"] != "complete":
                assert "研究排序" not in factor["score_rationale"]
                assert "评分为" not in factor["score_rationale"]
                assert not re.search(r"\d+(?:\.\d+)?\s*分", factor["score_rationale"])
            else:
                assert (
                    f"调整后分{float(factor['score_adjusted']):.1f}，"
                    f"原始分{float(factor['score_raw']):.1f}"
                    in factor["score_rationale"]
                )
            assert all(
                point["excerpt"] != point.get("excerpt_zh")
                for point in factor["information_points"]
                if not source_by_ref[
                    point["evidence_ref"].replace("source_ref:", "")
                ]["language"].lower().startswith("zh")
            )
            assert all(
                point.get("excerpt_zh")
                for point in factor["information_points"]
                if not source_by_ref[
                    point["evidence_ref"].replace("source_ref:", "")
                ]["language"].lower().startswith("zh")
            )
            assert all(
                not point.get("excerpt_zh")
                for point in factor["information_points"]
                if source_by_ref[
                    point["evidence_ref"].replace("source_ref:", "")
                ]["language"].lower().startswith("zh")
            )

    target_audit = pack["target_public_content_audit"]
    assert target_audit["status"] == "pass"
    assert target_audit["target_count"] == 7
    assert target_audit["duplicate_field_count"] == 0
    assert target_audit["role_overlap_failure_count"] == 0
    for field in (
        "conditional_investment_recommendation",
        "risk_note",
        "confirmed_scenario_action",
        "falsified_scenario_action",
    ):
        values = [target[field] for target in pack["entity_investment_targets"]]
        assert len(values) == len(set(values)) == 7

    huahai = targets_by_name["华海清科"]
    huahai_adjustment = next(
        point
        for point in huahai["target_data_points"]
        if point["metric_category"] == "corporate_action_adjustment"
    )
    huahai_valuation = next(
        point
        for point in huahai["target_data_points"]
        if point["metric_category"] == "current_valuation_and_profitability"
    )
    assert huahai_adjustment["evidence_ref_uri"] == "source_ref:FIN-EQ-HUHAI-DIVIDEND"
    assert "21.83元÷(1+0.39892)=15.6049元" in huahai_adjustment["value_text"]
    assert "除权同口径BPS 15.60元" in huahai_valuation["value_text"]
    assert huahai_valuation["additional_evidence_ref_uri_list"] == [
        "source_ref:FIN-EQ-HUHAI-DIVIDEND"
    ]
    pe_implied_price = 139.28 * 2.2186
    pb_implied_price = 19.80 * (21.83 / (1 + 0.39892))
    assert abs(pe_implied_price - pb_implied_price) / pe_implied_price < 0.001

    def iter_public_strings(value, path="pack"):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {
                    "excerpt",
                    "excerpt_zh",
                    "source_excerpt",
                    "source_excerpt_zh",
                    "local_locator",
                }:
                    continue
                yield from iter_public_strings(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from iter_public_strings(item, f"{path}[{index}]")
        elif isinstance(value, str):
            yield path, value

    public_strings = list(iter_public_strings(pack))
    for forbidden in (
        "WSPM",
        "下限模型",
        "供应商B1",
        "匿名供应商B1",
        "日本精工类",
        "只覆盖覆盖",
        "会使确认时间继续后移",
        "按按",
        "分开逐项比较",
        "TAM/SAM/SOM",
        "PE_TTM",
        "PS_TTM",
        "EPS_TTM",
        "E滚动市销率（PS-TTM）",
    ):
        violations = [path for path, text in public_strings if forbidden in text]
        assert not violations, f"{forbidden!r} 出现在：{violations[:8]}"
    assert any("滚动每股收益（EPS-TTM）" in text for _, text in public_strings)


def test_demand_pack_preserves_product_boundaries_and_factor_semantics() -> None:
    with tempfile.TemporaryDirectory() as directory:
        pack = build_demand_pack(output_dir=Path(directory))
    _assert_pack_core(pack, minimum_points=100, entity_count=7)
    assert len(pack["data_points"]) == 237
    assert pack["evidence_audit"]["data_points"]["series_merge_deduction"] == 11
    assert pack["evidence_audit"]["sources"]["created_count"] == 2
    names = {entity["display_name"] for entity in pack["entities"]}
    assert "200毫米成熟制程硅片需求" in names
    assert "SOI工程衬底需求" in names

    source_by_ref = {source["ref"]: source for source in pack["sources"]}
    assert source_by_ref["S067"]["title_zh"] == "中芯国际发布2025年第四季度业绩"
    assert source_by_ref["S068"]["title_zh"] == "中芯国际发布2024年第四季度业绩"
    assert any(point["source_ref"] == "S067" for point in pack["data_points"])
    assert any(point["source_ref"] == "S068" for point in pack["data_points"])
    for entity in pack["entities"]:
        for factor in entity["factor_scores"]:
            route = FACTOR_ROUTES[factor["factor_code"]]
            assert route["label"] in factor["metric_name"]
            assert route["question"] in factor["factor_topic_analysis"]
            refs = [value.replace("source_ref:", "") for value in factor["evidence_ref_uri_list"]]
            assert all(source_by_ref[ref]["source_tier"] in {"S", "A", "B"} for ref in refs)
            assert all(source_by_ref[ref]["source_review_status"] != "weak_source_only" for ref in refs)

    soitec_rows = [
        row for row in pack["entity_investment_targets"] if row["target_name"] == "Soitec"
    ]
    assert len(soitec_rows) == 1
    assert soitec_rows[0]["entity_key"] == "soi_engineered_substrate_demand"
    assert len(pack["entity_investment_targets"]) == 7
    assert pack["model_artifacts"]["financial_evidence_audit_sha256"].startswith(
        "sha256:"
    )
    assert pack["financial_evidence_audit"]["field_evidence_slice_count"] == 34
    targets_by_name = {
        target["target_name"]: target for target in pack["entity_investment_targets"]
    }
    eswin_2024 = next(
        point
        for point in targets_by_name["西安奕材"]["target_data_points"]
        if point.get("metric_category") == "financial_history"
        and point["period"] == "FY2024"
    )
    assert "2,121.45" in eswin_2024["value_text"]
    soitec = targets_by_name["Soitec"]
    assert soitec["evidence_ref_uri"] == "source_ref:FIN-SOITEC-03"
    soitec_2025 = next(
        point
        for point in soitec["target_data_points"]
        if point.get("metric_category") == "financial_history"
        and point["period"] == "FY2025"
    )
    assert "201.00" in soitec_2025["value_text"]
    globalwafers_2025 = [
        point
        for point in targets_by_name["环球晶圆"]["target_data_points"]
        if point.get("metric_category") == "financial_history"
        and point["period"] == "FY2025"
    ]
    assert len(globalwafers_2025) == 2
    assert {point["evidence_ref_uri"] for point in globalwafers_2025} == {
        "source_ref:FIN-GWC-01",
        "source_ref:FIN-GWC-03",
    }
    # Sparse, metric-specific evidence must not be replaced with synthetic
    # differentiation merely to make entity score vectors look distinct.
    assert all(
        entity["score_status"] == "insufficient_evidence"
        for entity in pack["entities"]
    )
    assert all(
        entity["score_quality_label"] == "unrated_insufficient_evidence"
        for entity in pack["entities"]
    )
    assert pack["metric_slot_chain_audit"][
        "all_usable_slots_have_exact_data_point_source_raw_standardized_chain"
    ] is True


def test_demand_model_keeps_global_total_and_public_project_floor_separate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output_dir = Path(directory)
        pack = build_demand_pack(output_dir=output_dir)
        model = json.loads((output_dir / "model_outputs.json").read_text(encoding="utf-8"))
    assert model["aggregate_300mm"]["scenarios"]["base"]["2028"]["300mm_capacity_wspm"] == 11_100_000
    assert model["official_200mm_capacity"]["scenarios"]["base"][0]["installed_200mm_wspm"] == 7_700_000
    assert model["coverage_warning"]["same_window_disclosed_projects"] == 2
    assert model["coverage_warning"]["total_projects_in_ledger"] == 36
    assert model["coverage_warning"]["same_window_disclosed_incremental_nameplate_wspm"] == 38_667
    assert model["coverage_warning"]["same_window_disclosed_share_of_global_increment_pct"] == pytest.approx(1.47)
    assert model["coverage_warning"]["excluded_from_same_window_project_ids"] == [
        "P005",
        "P036",
    ]
    assert model["soi_quantification_status"]["status"] == "not_quantified"
    assert "soi_demand_index" not in model
    assert all(item["pass"] for item in model["unit_reverse_checks"])
    assert pack["model_artifacts"]["model_inputs_sha256"].startswith("sha256:")
    assert pack["model_artifacts"]["model_code_sha256"].startswith("sha256:")
