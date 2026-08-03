from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

import pytest

from tools.opportunity_lens.build_silicon_wafer_demand_run_pack import (
    FACTOR_PUBLIC_REFS_BY_ENTITY,
    PUBLIC_FACT_CLUSTER_SOURCE_SPECS,
    PUBLIC_FACT_SOURCE_ALIAS,
    write_bundle,
)
from tools.opportunity_lens.manual_run_loader import load_pack, validate_pack_file


SOURCE_REF_PATTERN = re.compile(r"\^src:source_ref:([A-Za-z0-9_.-]+)")
USABLE_SLOT_STATUSES = {"available", "calculated", "stale_but_usable"}


@pytest.fixture(scope="module")
def demand_bundle(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, dict, dict, dict]:
    output_dir = tmp_path_factory.mktemp("silicon_wafer_demand")
    pack_path = write_bundle(output_dir=output_dir)
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    model_inputs = json.loads((output_dir / "model_inputs.json").read_text(encoding="utf-8"))
    model_outputs = json.loads((output_dir / "model_outputs.json").read_text(encoding="utf-8"))
    return output_dir, pack_path, pack, model_inputs, model_outputs


def test_supplemental_evidence_and_36_project_ledger_are_integrated(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, model_inputs, model_outputs = demand_bundle
    source_refs = {row["ref"] for row in pack["sources"]}
    assert {
        "DMD-SEMI-MEMORY-20260629",
        "DMD-SEMI-WAFER-OUTLOOK-202509",
        "DMD-NIST-GLOBALWAFERS",
        "DMD-UMC-FAB12I-CURRENT",
        "DMD-SAMSUNG-TAYLOR-20260610",
        "DMD-SILTRONIC-AR2025",
        "DMD-SEMI-300MM-OUTLOOK-2Q26",
        "DMD-SEMI-DEMAND-TRANSMISSION-20251008",
        "DMD-MICRON-SINGAPORE-20260127",
        "DMD-SK-SILTRON-SR2025",
        "DMD-PSMC-CURRENT-2026",
        "DMD-NEXCHIP-PHASE3-20240926",
        "DMD-SILAN-12INCH-ANALOG-20260105",
    } <= source_refs
    assert {
        "FIN-ESWIN-2025AR",
        "FIN-ESWIN-2026Q1",
        "FIN-SOITEC-FY2026",
    } <= source_refs
    assert len(pack["sources"]) == 121
    assert len(pack["data_points"]) == 237
    assert len(pack["project_ledger"]["projects"]) == 36
    assert len({row["fact_type"] for row in pack["data_points"]}) >= 3

    projects = {row["project_id"]: row for row in pack["project_ledger"]["projects"]}
    assert projects["P006"]["construction_start"] is None
    assert "目标" in projects["P006"]["status_as_of"]
    assert projects["P010"]["production_start"] is None
    assert "S068" in projects["P010"]["source_ids"]
    assert projects["P011"]["wspm"] is None
    assert projects["P012"]["full_capacity_date"] is None
    assert projects["P029"]["full_capacity_date"] is None
    assert projects["P030"]["wspm"] == 60_667
    assert "细分产品目前没有" in projects["P031"]["node"]
    assert projects["P034"]["node"] is None
    assert projects["P034"]["capacity_scope"] is None
    assert "node" not in projects["P034"]["field_evidence"]
    assert "capacity_scope" not in projects["P034"]["field_evidence"]

    assert projects["P035"]["wspm"] == 50_000
    assert projects["P035"]["construction_start"] is None
    assert projects["P035"]["production_start"] is None
    assert "当前施工和爬坡尚待更新" in projects["P035"]["capacity_scope"]
    assert "公开可量化项目子集" in projects["P035"]["model_treatment"]

    assert projects["P036"]["wspm"] == 20_000
    assert projects["P036"]["construction_start"] == "2026-01-04"
    assert "2027年第四季度" in projects["P036"]["production_start"]
    assert "2030" in projects["P036"]["full_capacity_date"]
    assert "已实现采购" in projects["P036"]["model_treatment"]
    assert "不能写成" in projects["P036"]["model_treatment"]

    quantified = {
        row["project_id"]: row
        for row in model_inputs["bottom_up_disclosed_increment_projects"]
    }
    assert set(quantified) == {"P005", "P012", "P029", "P036"}
    assert quantified["P012"]["full_capacity_year"] == 2028
    assert "研究假设" in quantified["P012"]["note"]
    assert quantified["P005"]["production_year_by_scenario"] == {
        "downside": 2028,
        "base": 2027,
        "upside": 2027,
    }
    assert quantified["P036"]["full_capacity_year"] == 2030
    assert model_outputs["coverage_warning"]["total_projects_in_ledger"] == 36
    assert "覆盖范围" in model_outputs["coverage_warning"]["interpretation"]
    assert "不能视为已实现采购的最低值" in model_outputs["coverage_warning"]["interpretation"]

    proxy = model_outputs["public_supply_demand_proxy"]
    assert proxy["equivalent_average_300mm_wafers_per_month_lower_bound"] == 8_214_432
    assert proxy["shipment_to_installed_capacity_ratio_lower_bound_pct"] == 74.0
    assert "不是供需缺口" in proxy["boundary"]

    dp122 = next(
        point for point in pack["data_points"] if point["data_point_key"] == "DP122"
    )
    assert dp122["extraction_method"] == "inferred"
    assert dp122["original_fact_type"] == "inferred"
    assert dp122["fact_type"] == "analyst_assumption"
    assert "4,000÷2=2,000" in dp122["note"]


def test_reader_facing_sections_have_exact_body_derived_sources_and_depth(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    assert len(pack["sections"]) == 6
    assert len(pack["entity_sections"]) == 7
    for section in [*pack["sections"], *pack["entity_sections"]]:
        body_refs = list(dict.fromkeys(SOURCE_REF_PATTERN.findall(section["body_markdown"])))
        declared_refs = [
            ref.removeprefix("source_ref:")
            for ref in section["evidence_ref_uri_list"]
        ]
        assert body_refs == declared_refs
    assert min(len(row["body_markdown"]) for row in pack["sections"]) >= 1_400
    assert min(len(row["body_markdown"]) for row in pack["entity_sections"]) >= 2_200

    targets = pack["entity_investment_targets"]
    assert len(targets) == 7
    assert len({row["target_name"] for row in targets}) == 7
    securities = [row for row in targets if row["target_type"] == "security"]
    observations = [row for row in targets if row["target_type"] == "basket"]
    assert len(securities) == 5
    assert len(observations) == 2
    assert {row["entity_key"] for row in targets} == {
        row["key"] for row in pack["entities"]
    }


def test_every_core_visual_row_has_a_source_citation(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    expected_keys = {
        "global_wafer_capacity_2026_2030",
        "global_fab_project_database",
        "china_fab_expansion_database",
        "project_demand_research_priority",
        "disclosed_incremental_capacity_ranking",
        "public_supply_demand_judgment_2026_2030",
        "global_wafer_supplier_competition",
        "china_300mm_supplier_ranking",
        "fab_wafer_supplier_relationships",
    }
    visuals = {row["block_key"]: row for row in pack["visuals"]}
    assert set(visuals) == expected_keys
    for key, visual in visuals.items():
        table = (
            visual["print_fallback"]
            if key == "global_wafer_capacity_2026_2030"
            else visual["display_data"]
        )
        assert table["columns"][-1] == "来源"
        assert table["rows"]
        assert all("^src:source_ref:" in str(row[-1]) for row in table["rows"])
        row_refs = {
            ref
            for row in table["rows"]
            for ref in SOURCE_REF_PATTERN.findall(str(row[-1]))
        }
        declared_refs = {
            ref.removeprefix("source_ref:")
            for ref in visual["evidence_ref_uri_list"]
        }
        assert row_refs == declared_refs
    assert len(visuals["global_fab_project_database"]["display_data"]["rows"]) == 36
    assert len(visuals["china_fab_expansion_database"]["display_data"]["rows"]) == 7
    assert len(visuals["disclosed_incremental_capacity_ranking"]["display_data"]["rows"]) == 4
    assert len(visuals["global_wafer_supplier_competition"]["display_data"]["rows"]) == 6
    assert len(visuals["china_300mm_supplier_ranking"]["display_data"]["rows"]) == 6
    assert "4个可量化项目基准情景" in visuals[
        "global_wafer_capacity_2026_2030"
    ]["print_fallback"]["columns"][4]


def test_source_locators_independence_and_staleness_are_audited(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    audit = pack["source_locator_audit"]
    assert audit["overall"] == {
        "required_count": 121,
        "precisely_located_count": 121,
        "coverage_rate": 1.0,
        "unknown_refs": [],
        "not_precisely_located_refs": [],
    }
    assert audit["public_core"]["required_count"] == 113
    assert audit["model_inputs"]["required_count"] == 15
    assert audit["usable_metric_slots"]["required_count"] == 10
    assert audit["generic_locator_count"] == 0
    assert audit["reference_only_count"] == 0

    by_url: dict[str, list[dict]] = defaultdict(list)
    for source in pack["sources"]:
        if source.get("url"):
            by_url[source["url"].lower().rstrip("/")].append(source)
        date = str(source.get("publish_date") or source.get("event_date") or "")
        if re.match(r"^(?:19|20)\d{2}", date) and int(date[:4]) <= 2024:
            assert str(source.get("temporal_warning") or "").startswith("严重时效提醒")
    for rows in by_url.values():
        if len(rows) < 2:
            continue
        assert len({row["independence_key"] for row in rows}) == 1
        assert len({row["source_tier"] for row in rows}) == 1
    assert len({row["independence_key"] for row in pack["sources"]}) == 104


def test_source_catalog_uses_exact_data_point_excerpt_and_same_point_translation(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    audit = pack["source_data_point_excerpt_audit"]
    assert audit["source_count_with_data_points"] == 82
    assert audit["aligned_source_count"] == 82
    assert audit["data_point_count_checked"] == 237
    assert audit["missing_direct_excerpt_count"] == 0
    assert audit["source_excerpt_mismatch_count"] == 0
    assert audit["translation_mismatch_count"] == 0
    assert audit["all_sources_with_data_points_use_exact_direct_excerpt"] is True

    points_by_ref: dict[str, dict[str, dict]] = defaultdict(dict)
    for point in pack["data_points"]:
        points_by_ref[point["source_ref"]][point["data_point_key"]] = point
    for source in pack["sources"]:
        if source["ref"] not in points_by_ref:
            continue
        key = source["excerpt_data_point_key"]
        point = points_by_ref[source["ref"]][key]
        assert source["excerpt"] == point["source_excerpt"]
        assert source["excerpt_zh"] == point.get("source_excerpt_zh", point["source_excerpt"])


def test_key_public_citations_open_fact_matching_source_drawers(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    output_dir, _, pack, _, _ = demand_bundle
    audit = pack["public_citation_excerpt_match_audit"]
    assert audit["fact_cluster_source_count"] == 13
    assert audit["supply_balance_row_count"] == 5
    assert audit["core_numeric_table_count"] == 3
    assert audit["core_numeric_row_count"] == 14
    assert audit["broad_source_ref_leak_count"] == 0
    assert audit["same_file_fact_clusters_reuse_independence_key"] is True
    assert audit["all_key_public_citations_open_matching_fact_excerpt"] is True
    assert (output_dir / "public_citation_excerpt_match_audit.json").exists()

    sources = {source["ref"]: source for source in pack["sources"]}
    points = {point["data_point_key"]: point for point in pack["data_points"]}
    public_text = json.dumps(
        {
            "sections": pack["sections"],
            "entity_sections": pack["entity_sections"],
            "visuals": pack["visuals"],
        },
        ensure_ascii=False,
    )
    for base_ref, alias_ref in PUBLIC_FACT_SOURCE_ALIAS.items():
        assert f"source_ref:{base_ref}" not in public_text
        assert f"source_ref:{alias_ref}" in public_text
        assert sources[alias_ref]["independence_key"] == sources[base_ref]["independence_key"]
        for point_key in PUBLIC_FACT_CLUSTER_SOURCE_SPECS[alias_ref]["data_point_keys"]:
            point = points[point_key]
            assert point["source_excerpt"] in sources[alias_ref]["excerpt"]
            assert point.get("source_excerpt_zh", point["source_excerpt"]) in sources[alias_ref]["excerpt_zh"]

    supply_visual = next(
        visual
        for visual in pack["visuals"]
        if visual["block_key"] == "public_supply_demand_judgment_2026_2030"
    )
    rows_by_year = {int(row[0]): row for row in supply_visual["display_data"]["rows"]}
    assert PUBLIC_FACT_SOURCE_ALIAS["S001"] in rows_by_year[2026][-1]
    assert PUBLIC_FACT_SOURCE_ALIAS["S064"] in rows_by_year[2027][-1]
    assert PUBLIC_FACT_SOURCE_ALIAS["S065"] in rows_by_year[2028][-1]
    assert "研究基准情景" in rows_by_year[2030][2]


def test_every_factor_information_point_matches_same_source_fact_and_translation(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    points_by_ref: dict[str, list[dict]] = defaultdict(list)
    for point in pack["data_points"]:
        points_by_ref[point["source_ref"]].append(point)
    sources = {source["ref"]: source for source in pack["sources"]}
    checked = 0
    critical: dict[tuple[str, str, str], dict] = {}
    for entity in pack["entities"]:
        for factor in entity["factor_scores"]:
            refs = [
                value.removeprefix("source_ref:")
                for value in factor["evidence_ref_uri_list"]
            ]
            assert len(refs) == len(factor["information_points"]) == 5
            for ref, information_point in zip(refs, factor["information_points"]):
                source = sources[ref]
                language = str(source.get("language") or "").lower()
                if language in {"zh", "zh-cn", "zh-tw", "chinese", "中文"}:
                    assert "excerpt_zh" not in information_point
                    matches = [
                        point
                        for point in points_by_ref.get(ref, [])
                        if point["source_excerpt"] == information_point["excerpt"]
                    ]
                else:
                    assert information_point.get("excerpt_zh")
                    matches = [
                        point
                        for point in points_by_ref.get(ref, [])
                        if point["source_excerpt"] == information_point["excerpt"]
                        and point.get("source_excerpt_zh")
                        == information_point["excerpt_zh"]
                    ]
                if points_by_ref.get(ref):
                    assert matches
                else:
                    assert information_point["excerpt"] == source["excerpt"]
                    if language not in {"zh", "zh-cn", "zh-tw", "chinese", "中文"}:
                        assert information_point["excerpt_zh"] == source["excerpt_zh"]
                checked += 1
                critical[(entity["key"], factor["factor_code"], ref)] = information_point
    assert checked == 350
    global_capacity = critical[
        (
            "global_300mm_fab_expansion",
            "demand.customer_capex_capacity_signal",
            "S001",
        )
    ]
    advanced_logic = critical[
        (
            "advanced_logic_wafer_demand",
            "demand.application_intensity_change",
            "S001",
        )
    ]
    assert "11.1 million wafers per month" in global_capacity["excerpt"]
    assert "850,000 wpm" in advanced_logic["excerpt"]
    assert "1.4 million wpm" in advanced_logic["excerpt"]
    audit = pack["factor_information_point_audit"]
    assert audit["information_point_count"] == 350
    assert audit["all_information_points_pass"] is True


def test_history_current_financials_and_public_model_rows_are_explicit(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    report_text = "\n".join(row["body_markdown"] for row in pack["sections"])
    entity_text = "\n".join(row["body_markdown"] for row in pack["entity_sections"])
    assert "2020年以来的周期回溯" in report_text
    assert "12,407" in report_text and "14,713" in report_text
    assert "2026—2030与上一轮不同" in report_text
    assert "从上一轮扩产周期得到的约束" in entity_text
    assert "存储周期与本轮差异" in entity_text
    assert "2020年以来的成熟制程周期" in entity_text

    sources = {source["ref"]: source for source in pack["sources"]}
    assert sources["FIN-ESWIN-2025AR"]["url"].endswith("1225128935.PDF")
    assert sources["FIN-ESWIN-2026Q1"]["url"].endswith("1225128959.PDF")
    assert "soitec-fy%2726-pr" in sources["FIN-SOITEC-FY2026"]["url"].lower()
    targets = {row["target_name"]: row for row in pack["entity_investment_targets"]}
    eswin_points = targets["西安奕材"]["target_data_points"]
    soitec_points = targets["Soitec"]["target_data_points"]
    assert any(row["period"] == "Q1 2026" and "毛利率2.58%" in row["value_text"] for row in eswin_points)
    assert any(row["period"] == "FY2025" and "主营业务毛利率3.44%" in row["value_text"] for row in eswin_points)
    assert any(row["period"] == "FY2026" and "毛利率16.30%" in row["value_text"] for row in soitec_points)
    assert any(row["period"] == "FY2025-FY2026" and "-0.23升至0.63" in row["value_text"] for row in soitec_points)
    assert pack["model_artifacts"]["shared_financial_targets_sha256"].startswith("sha256:")
    assert pack["model_artifacts"]["shared_financial_sources_sha256"].startswith("sha256:")
    assert pack["model_artifacts"]["demand_financial_updates_sha256"].startswith("sha256:")

    supply_visual = next(
        row
        for row in pack["visuals"]
        if row["block_key"] == "public_supply_demand_judgment_2026_2030"
    )
    rows_by_year = {row[0]: row for row in supply_visual["display_data"]["rows"]}
    assert "2029模型值×1.04" in rows_by_year[2030][2]
    assert "2029模型值×1.02" in rows_by_year[2030][2]
    assert PUBLIC_FACT_SOURCE_ALIAS["S064"] in rows_by_year[2030][-1]
    assert PUBLIC_FACT_SOURCE_ALIAS["S065"] in rows_by_year[2030][-1]


def test_315_slot_cross_audit_context_and_unrated_public_text(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    audit = pack["metric_slot_cross_audit"]
    assert audit["slot_count"] == 315
    assert sum(audit["classification_counts"].values()) == 315
    assert audit["classification_counts"]["exact_slot_match"] == 15
    assert audit["classification_counts"]["contextual_evidence_only"] == 2
    assert audit["project_ledger_context"]["grade_a_project_count"] == 30
    assert audit["project_ledger_context"]["quantifiable_project_count"] == 4

    slots: dict[tuple[str, str, str], dict] = {}
    for entity in pack["entities"]:
        for factor in entity["factor_scores"]:
            if factor["score_status"] != "complete":
                public_text = "\n".join(
                    [
                        factor["score_rationale"],
                        factor["factor_value_summary"],
                        factor["source_context_summary"],
                        factor["factor_topic_analysis"],
                        *factor["theme_analysis_points"],
                    ]
                )
                assert "暂不评分" in factor["score_rationale"]
                assert re.search(r"\d+(?:\.\d+)?分|研究排序|评分为", public_text) is None
            for slot in factor["metric_slots"]:
                slots[(entity["key"], factor["factor_code"], slot["slot_code"])] = slot
    assert slots[("global_300mm_fab_expansion", "supply.capacity_event_12m", "planned_or_rumored_capacity")]["data_point_keys"] == ["DP236"]
    assert slots[("mature_200mm_wafer_demand", "supply.capacity_event_12m", "planned_or_rumored_capacity")]["data_point_keys"] == ["DP241"]
    slack = slots[("mature_200mm_wafer_demand", "demand.downstream_price_momentum", "price_reversal_signal")]
    assert slack["contextual_data_point_keys"] == ["DP178"]
    assert "没有该槽要求的同口径价格变化值" in slack["raw_value_text"]

    public_text = json.dumps(
        {
            "sections": pack["sections"],
            "entity_sections": pack["entity_sections"],
            "visuals": pack["visuals"],
            "targets": pack["entity_investment_targets"],
        },
        ensure_ascii=False,
    )
    assert "WSPM" not in public_text
    assert "底部精确求和" not in public_text
    assert "精确底部求和" not in public_text

    score_audit = pack["factor_public_score_consistency_audit"]
    assert score_audit["complete_factor_count"] == 1
    assert score_audit["unrated_factor_count"] == 69
    assert score_audit["all_complete_factors_use_only_raw_and_adjusted_scores"] is True
    assert score_audit["all_unrated_factors_exclude_scores_and_rankings"] is True
    assert score_audit["found_template_phrases"] == []
    complete_row = score_audit["complete_factor_rows"][0]
    assert complete_row["public_score_mentions"] == [49.25, 49.0]
    assert complete_row["third_score_mentions"] == []


def test_public_factor_analysis_is_distinct_and_uses_only_curated_role_sources(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    for entity in pack["entities"]:
        factor_rows = entity["factor_scores"]
        analyses = [row["factor_topic_analysis"] for row in factor_rows]
        assert len(analyses) == len(set(analyses)) == 10
        similarities = [
            SequenceMatcher(None, left, right).ratio()
            for index, left in enumerate(analyses)
            for right in analyses[index + 1 :]
        ]
        assert max(similarities) < 0.55
        for factor in factor_rows:
            code = factor["factor_code"]
            refs = {
                value.removeprefix("source_ref:")
                for value in factor["evidence_ref_uri_list"]
            }
            assert refs == set(FACTOR_PUBLIC_REFS_BY_ENTITY[entity["key"]][code])
            assert len(refs) == 5
            combined = " ".join(
                str(factor[field])
                for field in (
                    "score_rationale",
                    "source_context_summary",
                    "factor_topic_analysis",
                )
            )
            assert "程序只把" not in combined
            assert "页面中的中性基准" not in combined
            assert "字段状态" not in combined


def test_target_decisions_are_product_and_company_specific(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    targets = pack["entity_investment_targets"]
    for field in (
        "confirmed_scenario_action",
        "falsified_scenario_action",
        "conditional_investment_recommendation",
    ):
        assert len({row[field] for row in targets}) == len(targets)
    by_name = {row["target_name"]: row for row in targets}
    assert "新加坡厂" in by_name["世创电子材料"]["confirmed_scenario_action"]
    assert "十年供货" in by_name["环球晶圆"]["confirmed_scenario_action"]
    assert "先进300毫米" in by_name["SUMCO"]["confirmed_scenario_action"]
    assert "良率" in by_name["西安奕材"]["confirmed_scenario_action"]
    assert "RF-SOI" in by_name["Soitec"]["confirmed_scenario_action"]
    assert "NAND" in by_name["NAND硅片供需观察篮子"][
        "conditional_investment_recommendation"
    ]
    assert "纯200毫米" in by_name["200毫米硅片供需观察篮子"][
        "conditional_investment_recommendation"
    ]


def test_metric_slots_use_exact_v081_rules_and_context_never_scores(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, _ = demand_bundle
    audit = pack["metric_slot_chain_audit"]
    assert audit["factor_count"] == 70
    assert audit["total_slot_count"] == 315
    assert audit["usable_scored_slot_count"] == 11
    assert audit["usable_context_slot_count"] == 4
    assert audit["usable_slot_count"] == 15
    assert audit["unique_linked_data_point_count"] == 14
    assert audit["unique_linked_source_count"] == 10
    assert all(row["pass"] for row in audit["coverage_rechecks"])

    slots: dict[tuple[str, str, str], dict] = {}
    for entity in pack["entities"]:
        for factor in entity["factor_scores"]:
            for slot in factor["metric_slots"]:
                if slot["value_status"] in USABLE_SLOT_STATUSES:
                    slots[(entity["key"], factor["factor_code"], slot["slot_code"])] = slot
                    assert len(slot["data_point_keys"]) == 1
                    assert len(slot["source_refs"]) == 1
                    assert slot.get("raw_value_num") is not None or slot.get("raw_value_text")
                    assert slot.get("standardized_value_num") is not None or slot.get(
                        "standardized_value_text"
                    )
                    assert slot["normalization_method"]
                    if slot["slot_role"] == "context":
                        assert "slot_score" not in slot
                        assert "bucket" not in slot
                        assert "scoring_rule" not in slot

    global_output = slots[
        (
            "global_300mm_fab_expansion",
            "demand.output_consumption_proxy",
            "output_or_shipment_growth_3m",
        )
    ]
    assert global_output["data_point_keys"] == ["DP251"]
    assert global_output["standardized_value_num"] == -4.7
    assert global_output["slot_score"] == 45.0

    china_sales = slots[
        (
            "china_300mm_wafer_suppliers",
            "demand.output_consumption_proxy",
            "output_or_shipment_growth_3m",
        )
    ]
    assert china_sales["data_point_keys"] == ["DP199"]
    assert china_sales["standardized_value_num"] == pytest.approx(33.259663)
    assert china_sales["slot_score"] == 90.0

    china_price = slots[
        (
            "china_300mm_wafer_suppliers",
            "signal.material_price_momentum",
            "material_price_yoy_change",
        )
    ]
    assert china_price["data_point_keys"] == ["DP199"]
    assert china_price["standardized_value_num"] == pytest.approx(-12.101477)
    assert china_price["slot_score"] == 25.0

    current_capacity = slots[
        (
            "china_300mm_wafer_suppliers",
            "supply.capacity_event_12m",
            "current_effective_capacity",
        )
    ]
    assert current_capacity["standardized_value_num"] == pytest.approx(30.583333)
    assert current_capacity["standardized_unit"] == "万片/月"
    assert current_capacity["slot_score"] == 50.0

    advanced_delay = slots[
        (
            "advanced_logic_wafer_demand",
            "demand.customer_capex_capacity_signal",
            "customer_delay_or_cut_event",
        )
    ]
    assert advanced_delay["data_point_keys"] == ["DP060"]
    assert advanced_delay["slot_score"] == 20.0

    planned = slots[
        (
            "china_300mm_wafer_suppliers",
            "supply.capacity_event_12m",
            "planned_or_rumored_capacity",
        )
    ]
    assert planned["standardized_value_num"] == 120.0
    assert "slot_score" not in planned

    # The strict per-entity router must not reuse one Chinese supplier price
    # as a global, DRAM or NAND price signal.
    assert not any(
        slot["data_point_keys"] == ["DP206"]
        for key, slot in slots.items()
        if key[0] != "china_300mm_wafer_suppliers"
    )


def test_project_scenario_is_not_mislabeled_as_procurement_lower_bound(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, _, pack, _, model_outputs = demand_bundle
    public_text = json.dumps(
        {
            "sections": pack["sections"],
            "entity_sections": pack["entity_sections"],
            "visuals": pack["visuals"],
            "project_ledger": pack["project_ledger"],
        },
        ensure_ascii=False,
    )
    assert "四项目采购下限" not in public_text
    assert "进入公开项目下限" not in public_text
    assert "进入2026—2030采购下限" not in public_text
    assert "下限模型" not in public_text
    assert "采购下限" not in public_text
    assert "公开可量化项目子集" in public_text
    assert "4个可量化项目基准情景" in public_text
    assert "不能视为已实现采购的最低值" in model_outputs["coverage_warning"]["interpretation"]


def test_pack_validates_and_loads_into_temporary_database_only(
    demand_bundle: tuple[Path, Path, dict, dict, dict],
) -> None:
    _, pack_path, pack, _, _ = demand_bundle
    validation = validate_pack_file(pack_path, publication_mode="validate")
    assert validation["valid"] is True

    temp_dir = Path("cache/opportunity_lens/test_temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    db_path = temp_dir / f"opportunity_lens_demand_{uuid4().hex}.db"
    try:
        run_id = load_pack(pack_path, db_path=db_path, publication_mode="stage")
        assert run_id > 0
        with closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute(
                "SELECT id, run_status, run_readiness_status FROM opportunity_run WHERE id=?",
                (run_id,),
            ).fetchone()
            assert row == (run_id, "under_review", "reviewable")
            source_count = conn.execute(
                "SELECT COUNT(*) FROM opportunity_source WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            entity_count = conn.execute(
                "SELECT COUNT(*) FROM opportunity_entity_maturation WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            assert source_count == 121
            assert entity_count == 7
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)
