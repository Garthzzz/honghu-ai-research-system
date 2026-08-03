from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from tools.opportunity_lens.build_silicon_wafer_equipment_run_pack import build_pack
from tools.opportunity_lens.run_pack_contract import validate_run_pack


SECTION_REF_RE = re.compile(r"\^src:source_ref:([A-Za-z0-9_-]+)")


def _build() -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory() as directory:
        output_dir = Path(directory)
        pack = build_pack(output_dir=output_dir)
        model = json.loads(
            (output_dir / "model_outputs.json").read_text(encoding="utf-8")
        )
    return pack, model


def _body_refs(body: str) -> list[str]:
    return list(dict.fromkeys(SECTION_REF_RE.findall(body)))


def test_equipment_pack_answers_market_chain_and_supplier_questions() -> None:
    pack, model = _build()
    report = validate_run_pack(pack, publication_mode="stage")
    assert report.valid, report.as_dict()
    source_refs = [source["ref"] for source in pack["sources"]]
    assert len(source_refs) == len(set(source_refs))
    assert {
        "FIN-EQ-PVA-MARKET",
        "FIN-EQ-ACCRETECH-MARKET",
        "FIN-EQ-JINGSHENG-MARKET",
        "FIN-EQ-KLA-MARKET",
    } <= set(source_refs)
    assert len(pack["data_points"]) == 154
    assert pack["evidence_audit"]["data_points"]["final_retained_count"] == 154
    assert pack["evidence_audit"]["data_points"]["final_itemized_audit_count"] == 154
    assert pack["evidence_audit"]["data_points"]["final_itemized_audit_failure_count"] == 0
    assert len(pack["entities"]) == 5

    keys = [visual["block_key"] for visual in pack["visuals"]]
    required_visuals = {
        "equipment_market_space_results",
        "demand_wafer_process_supplier_chain",
        "wafer_maker_equipment_project_database",
        "silicon_wafer_equipment_chain_map",
        "soi_proprietary_process_chain",
        "wafer_maker_equipment_supplier_relationships",
        "named_supplier_inclusion_observation_exclusion",
        "listed_equipment_company_evidence_ranking",
        "listed_equipment_company_financial_snapshot",
    }
    assert required_visuals <= set(keys)
    assert len(keys) == len(set(keys))
    rows_by_key = {
        visual["block_key"]: visual["display_data"]["rows"]
        for visual in pack["visuals"]
    }
    market_rows = rows_by_key["equipment_market_space_results"]
    assert _body_refs(market_rows[0][-1]) == ["S066", "S011"]
    assert _body_refs(market_rows[1][-1]) == [
        "S066",
        "S068",
        "S072",
        "S073",
        "S011",
    ]
    assert all(
        _body_refs(row[-1]) == ["S066", "S068", "S072", "S073", "S011"]
        for row in market_rows[2:]
    )
    assert all(
        "不是公开国产化率" in row[3]
        for row in market_rows
        if row[0].startswith("中国厂商可服务金额")
    )
    assert len(rows_by_key["demand_wafer_process_supplier_chain"]) == 6
    assert len(rows_by_key["wafer_maker_equipment_project_database"]) == 22
    assert len(rows_by_key["soi_proprietary_process_chain"]) == 9
    # 删除了两条把晶升股份历史订单误归给晶盛机电的关系后，
    # 公开关系矩阵只保留 29 条可由当前证据支持的记录。
    assert len(rows_by_key["wafer_maker_equipment_supplier_relationships"]) == 29
    assert len(rows_by_key["named_supplier_inclusion_observation_exclusion"]) == 22
    assert len(rows_by_key["listed_equipment_company_evidence_ranking"]) == 10
    assert len(rows_by_key["listed_equipment_company_financial_snapshot"]) == 7
    assert all(
        len(row) == 6 and _body_refs(str(row[-1]))
        for row in rows_by_key["listed_equipment_company_financial_snapshot"]
    )
    assert any("Shin-Etsu" in row[0] and "未找到2026—2030" in row[5]
               for row in rows_by_key["wafer_maker_equipment_project_database"])
    assert all("匿名传闻" not in row[0] for row in rows_by_key["wafer_maker_equipment_project_database"])
    assert len(pack["project_ledger"]["projects"]) == 23
    public_supplier_names = {
        row[0]
        for row in rows_by_key["named_supplier_inclusion_observation_exclusion"]
    }
    assert not {
        "精测电子",
        "沈阳科仪",
        "Lam Research",
        "Tokyo Electron / TEL",
        "日本精工相关设备企业",
    } & public_supplier_names
    assert len(pack["negative_supplier_search_logs"]) == 5
    assert all(row["searched_on"] == "2026-07-19" for row in pack["negative_supplier_search_logs"])
    projects = {row["project_id"]: row for row in pack["project_ledger"]["projects"]}
    assert projects["PRJ012"]["status"] == "historical_status_not_currently_verified"
    assert projects["PRJ015"]["status"] == "pending_current_update"
    assert "基础情景" not in projects["PRJ008"]["equipment_demand_treatment"]


def test_equipment_market_space_is_reproducible_and_does_not_fabricate_tam() -> None:
    pack, model = _build()
    market = model["market_space"]
    global_market = market["global_equipment_demand"]
    assert global_market["quantified_amount_rmb_100m"] is None
    assert global_market["upper_bound"] is None
    assert global_market["central_estimate"] is None
    assert "武汉条件情景不能当作全球下限" in global_market["reason"]
    wuhan = market["wuhan_complete_build_conditional_rmb_100m"]
    assert wuhan["low"] == pytest.approx(66.9228192)
    assert wuhan["high"] == pytest.approx(81.4521636)
    china = market["current_quantifiable_four_project_scenario_rmb_100m"]
    assert china["low"] == pytest.approx(66.9228192)
    assert china["high"] == pytest.approx(146.4038096065)
    assert "不是中国全部已识别项目的上限" in china["excluded_scope"]

    sam = market["china_serviceable_market_sensitivity"]
    assert [row["scenario"] for row in sam] == [
        "窄覆盖情景",
        "中等覆盖敏感性",
        "宽覆盖压力测试",
    ]
    assert sam[0]["combined_multiplier"] == pytest.approx(0.09375)
    assert sam[0]["serviceable_amount_rmb_100m"]["low"] == pytest.approx(
        6.2740143
    )
    assert sam[2]["serviceable_amount_rmb_100m"]["high"] == pytest.approx(
        79.0580572
    )
    company = market["company_amount_sensitivity"]
    assert len(company) == 12
    assert company[0]["serviceable_scenario"] == "窄覆盖情景"
    assert company[0]["assumed_combined_share"] == 0.01
    assert company[0]["equipment_amount_rmb_100m"]["low"] == pytest.approx(
        0.062740143
    )
    assert company[-1]["equipment_amount_rmb_100m"]["high"] == pytest.approx(
        7.905805718751
    )

    assert "semi_area_scenarios" not in model
    assert "project_demand" not in model
    assert "annual_totals_rmb_100m" not in model["equipment_scenario_analysis"]
    intensity = model["equipment_budget_per_100k_wspm_rmb_100m"][
        "300毫米完整抛光片生产线"
    ]
    assert intensity["low"] == pytest.approx(11.1538033333)
    assert intensity["high"] == pytest.approx(13.5753606)
    assert model["equipment_project_pool"][0]["conditional_execution_switch"] == 1
    assert "execution_probability" not in model["equipment_project_pool"][0]
    report_text = "\n".join(section["body_markdown"] for section in pack["sections"])
    assert "0.67—1.46亿元" not in report_text
    assert "中等覆盖敏感性下，1%、5%和10%综合份额" in report_text


def test_sections_and_core_table_rows_have_exact_clickable_evidence() -> None:
    pack, _model = _build()
    for section in [*pack["sections"], *pack["entity_sections"]]:
        refs = _body_refs(section["body_markdown"])
        assert refs
        assert section["evidence_ref_uri_list"] == [
            f"source_ref:{ref}" for ref in refs
        ]

    for visual in pack["visuals"]:
        declared = {
            value.replace("source_ref:", "")
            for value in visual["evidence_ref_uri_list"]
        }
        for row in visual["display_data"]["rows"]:
            row_refs = set(SECTION_REF_RE.findall(str(row[-1])))
            assert row_refs, (visual["block_key"], row)
            assert row_refs <= declared

    source_by_ref = {source["ref"]: source for source in pack["sources"]}
    generic_locators = {"", "原始网页或PDF所列段落", "原始网页所列段落"}
    public_refs = set()
    for value in [
        pack["sections"],
        pack["entity_sections"],
        pack["entity_investment_targets"],
        pack["visuals"],
    ]:
        public_refs.update(_body_refs(json.dumps(value, ensure_ascii=False)))
    assert public_refs
    assert all(
        str(source_by_ref[ref].get("local_locator") or "").strip()
        not in generic_locators
        for ref in public_refs
    )


def test_targets_are_unique_and_public_language_has_no_production_templates() -> None:
    pack, _model = _build()
    targets = pack["entity_investment_targets"]
    assert len(targets) == 7
    assert len({target["ticker"] for target in targets}) == len(targets)
    assert {target["target_name"] for target in targets} == {
        "PVA TePla",
        "东京精密／ACCRETECH",
        "晶盛机电",
        "KLA",
        "晶升股份",
        "Applied Materials",
        "华海清科",
    }
    assert {target["entity_key"] for target in targets} == {
        entity["key"] for entity in pack["entities"]
    }
    assert all(target["target_data_points"] for target in targets)
    targets_by_name = {target["target_name"]: target for target in targets}
    for name, expected_history_count in {
        "晶升股份": 3,
        "Applied Materials": 4,
        "华海清科": 3,
    }.items():
        history = [
            point
            for point in targets_by_name[name]["target_data_points"]
            if point.get("metric_category") == "financial_history"
        ]
        assert len(history) == expected_history_count
        assert all("经营现金流" in point["value_text"] for point in history)
        assert all("资本开支" in point["value_text"] for point in history)
        assert any(
            point.get("metric_category") == "current_valuation_and_profitability"
            for point in targets_by_name[name]["target_data_points"]
        )
    assert all(
        any(
            point.get("metric_category") == "current_valuation_and_profitability"
            for point in target["target_data_points"]
        )
        for target in targets
    )
    assert "当前市盈率也不适用" in targets_by_name["晶升股份"]["target_deep_research_markdown"]
    assert pack["financial_evidence_audit"]["audited_target_count"] == 7
    assert pack["financial_evidence_audit"]["current_valuation_point_count"] == 7

    public_text = json.dumps(
        {
            "sections": pack["sections"],
            "entity_sections": pack["entity_sections"],
            "targets": targets,
            "visuals": pack["visuals"],
        },
        ensure_ascii=False,
    )
    for forbidden in (
        "下一轮用",
        "当前代理",
        "若若",
        "可以认为可以认为",
        "。，",
        "参数 owner",
        "输出覆盖卡",
        "决策验证债",
    ):
        assert forbidden not in public_text

    assert all(
        point["interpretation"] != point["research_use"]
        for point in pack["data_points"]
    )
    source_by_ref = {source["ref"]: source for source in pack["sources"]}
    for ref in ("S030", "S043", "S063", "FIN-PVA-02"):
        assert source_by_ref[ref]["source_review_status"] == "stale"
        assert source_by_ref[ref]["staleness_warning"]
    assert source_by_ref["S064"]["local_locator"].startswith("PDF第12页")
    assert source_by_ref["S034"]["independence_key"] == source_by_ref["FIN-KLA-02"]["independence_key"]
    assert source_by_ref["S050"]["independence_key"] == source_by_ref["FIN-ACC-03"]["independence_key"]
    assert source_by_ref["S042"]["independence_key"] == source_by_ref["FIN-PVA-03"]["independence_key"]
    assert pack["model_artifacts"]["model_code_sha256"].startswith("sha256:")
    assert pack["model_artifacts"]["final_data_point_evidence_audit_sha256"].startswith("sha256:")
    assert pack["model_artifacts"]["critical_public_fact_citation_audit_sha256"].startswith("sha256:")


def test_critical_public_rows_use_fact_specific_excerpts() -> None:
    pack, _model = _build()
    audit = pack["critical_public_fact_citation_audit"]
    assert audit["status"] == "pass"
    assert audit["failure_count"] == 0
    assert audit["audited_public_row_count"] == 16

    source_by_ref = {source["ref"]: source for source in pack["sources"]}
    required_source_tokens = {
        "S066": ("30万片/月", "334,614.10万元", "50万片/月", "678,768.03万元"),
        "S072": ("480万片", "601,905.00万元", "294,763.26万元", "48.97%"),
        "S073": ("180万片", "23.02亿元", "20.60%", "2027年12月"),
        "S074": ("180万片", "22.62亿元", "96万片", "12.30亿元"),
        "S075": ("5台化学机械抛光设备", "79%", "2台设备", "尚未完成合同验收"),
        "S076": ("3台研磨减薄设备", "尚未通过验收", "90%"),
        "S077": ("1.87亿元", "1.94亿元", "1.15亿元", "4.49亿元", "超过5亿元", "约3亿元"),
        "S078": ("67.10亿元", "2024年末", "30万片/月"),
        "S079": ("2015年", "上海新昇", "2018年", "立昂微", "TCL中环"),
        "S080": ("2022.04.27", "研磨机", "2,937.60万美元", "正在履行"),
        "S081": ("Okamoto", "终端生产商", "直接合作"),
        "S082": ("710,733.24", "141,869.86", "567,596.55"),
        "FIN-PVA-06": ("156,624", "60,005", "37.7%", "internal segment revenue"),
    }
    for ref, tokens in required_source_tokens.items():
        excerpt = source_by_ref[ref]["excerpt"]
        assert all(token in excerpt for token in tokens), (ref, excerpt)

    rows_by_key = {
        visual["block_key"]: visual["display_data"]["rows"]
        for visual in pack["visuals"]
    }
    project_rows = rows_by_key["wafer_maker_equipment_project_database"]
    expected_project_refs = {
        "沪硅产业/上海新昇": ["S078", "S066"],
        "12英寸全流程硅片": ["S072"],
        "12英寸外延片": ["S073"],
        "12英寸轻掺外延片": ["S074"],
        "12英寸重掺衬底片": ["S074"],
    }
    for marker, expected_refs in expected_project_refs.items():
        rows = [row for row in project_rows if marker in " ".join(map(str, row))]
        assert len(rows) == 1, marker
        assert _body_refs(str(rows[0][-1])) == expected_refs

    supplier_rows = rows_by_key["wafer_maker_equipment_supplier_relationships"]
    for segment, expected_ref in {
        "CMP/最终抛光": "S075",
        "研磨减薄": "S076",
        "12英寸单晶生长": "S077",
    }.items():
        row = next(
            row
            for row in supplier_rows
            if row[0] == "西安奕材" and row[1] == segment
        )
        assert expected_ref in _body_refs(str(row[-1]))

    report_text = "\n".join(section["body_markdown"] for section in pack["sections"])
    assert all(f"^src:source_ref:{ref}" in report_text for ref in ("S072", "S073", "S074", "S075", "S076"))
    assert "^src:source_ref:S003" not in report_text
    assert "^src:source_ref:S005" not in report_text


def test_fact_specific_provenance_is_consistent_across_raw_and_public_outputs() -> None:
    pack, _model = _build()

    projects = {
        project["project_id"]: project
        for project in pack["project_ledger"]["projects"]
    }
    assert projects["PRJ004"]["source_ids"] == ["S011", "S012", "S066"]
    assert projects["PRJ005"]["source_ids"] == [
        "S067",
        "S082",
        "S069",
        "S070",
        "S080",
        "S081",
        "S071",
    ]

    relations = pack["equipment_landscape"]["supplier_relations"]
    serialized_relations = json.dumps(relations, ensure_ascii=False)
    assert "晶盛机电2021年向上海新昇供应2台" not in serialized_relations
    assert "晶盛机电2018年向金瑞泓交付2台" not in serialized_relations
    assert any(
        row["supplier"] == "晶升股份"
        and row["wafer_company_or_project"] == "沪硅产业/上海新昇"
        and row["source_ids"] == ["S079"]
        for row in relations
    )
    assert any(
        row["supplier"] == "Applied Materials"
        and row["source_ids"][:1] == ["S069"]
        for row in relations
    )
    assert any(
        row["supplier"] == "KLA"
        and row["source_ids"][:1] == ["S070"]
        for row in relations
    )
    assert any(
        "匿名研磨设备供应商" in row["supplier"]
        and row["source_ids"] == ["S080"]
        for row in relations
    )
    assert any(
        "Okamoto" in row["supplier"]
        and row["source_ids"] == ["S081"]
        and "具体机型和本轮项目合同未披露" in row["status_detail"]
        for row in relations
    )

    points = {point["data_point_key"]: point for point in pack["data_points"]}
    assert points["equipment_dp_053"]["source_ref"] == "S082"
    assert points["equipment_dp_054"]["source_ref"] == "S069"
    assert points["equipment_dp_056"]["source_ref"] == "S080"
    assert points["equipment_dp_057"]["source_ref"] == "S070"

    target_refs = {
        target["target_name"]: target["evidence_ref_uri"]
        for target in pack["entity_investment_targets"]
    }
    assert target_refs["PVA TePla"] == "source_ref:FIN-PVA-02"
    assert target_refs["东京精密／ACCRETECH"] == "source_ref:FIN-ACC-03"
    assert target_refs["KLA"] == "source_ref:S070"
    assert target_refs["晶升股份"] == "source_ref:S079"
    assert target_refs["Applied Materials"] == "source_ref:S069"

    amat = next(
        target
        for target in pack["entity_investment_targets"]
        if target["target_name"] == "Applied Materials"
    )
    amat_valuation = next(
        point
        for point in amat["target_data_points"]
        if point.get("metric_category") == "current_valuation_and_profitability"
    )
    assert "PS-TTM）接口未返回、当前不可得" in amat_valuation["value_text"]

    public_text = json.dumps(
        {
            "sections": pack["sections"],
            "visuals": pack["visuals"],
            "targets": pack["entity_investment_targets"],
        },
        ensure_ascii=False,
    )
    assert "晶盛机电12英寸SOI键合设备处于验证阶段" not in public_text
    assert "上海超硅披露自制能力" not in public_text
    assert "披露毛利率37.7%按含内部收入的分部总收入计算" in public_text


def test_equipment_metric_slots_use_semantic_data_points_and_protocol_boundaries() -> None:
    pack, _model = _build()
    entities = {entity["key"]: entity for entity in pack["entities"]}

    for entity in pack["entities"]:
        factors = {factor["factor_code"]: factor for factor in entity["factor_scores"]}
        output_slot = next(
            slot
            for slot in factors["demand.output_consumption_proxy"]["metric_slots"]
            if slot["slot_code"] == "output_or_shipment_growth_3m"
        )
        assert output_slot["value_status"] == "not_found_after_search"
        assert not output_slot.get("data_point_keys")
        sales_slot = next(
            slot
            for slot in factors["demand.output_consumption_proxy"]["metric_slots"]
            if slot["slot_code"] == "industry_sales_growth"
        )
        assert sales_slot["standardized_value_num"] == pytest.approx(-1.2)
        assert sales_slot["slot_score"] == pytest.approx(45.0)

        for factor in entity["factor_scores"]:
            for slot in factor["metric_slots"]:
                if slot["value_status"] == "not_found_after_search":
                    assert not slot.get("data_point_keys")
                    continue
                assert slot.get("data_point_keys")
                assert slot.get("data_point_titles")
                assert slot.get("standardized_unit")
                assert slot.get("normalization_method")

    grinding = {
        factor["factor_code"]: factor
        for factor in entities["wafer_grinding_polishing_tools"]["factor_scores"]
    }
    order_slot = next(
        slot
        for slot in grinding["demand.customer_capex_capacity_signal"]["metric_slots"]
        if slot["slot_code"] == "equipment_order_or_billings_proxy"
    )
    assert order_slot["data_point_titles"] == [
        "上海超硅-招股书匿名研磨设备供应商：研磨机合同金额"
    ]
    assert all("月产能" not in title for title in order_slot["data_point_titles"])

    epitaxy = {
        factor["factor_code"]: factor
        for factor in entities["silicon_epitaxy_tools"]["factor_scores"]
    }
    cycle_slot = next(
        slot
        for slot in epitaxy["supply.expansion_cycle_bucket"]["metric_slots"]
        if slot["slot_code"] == "expansion_cycle_months_or_bucket"
    )
    assert cycle_slot["standardized_value_num"] == pytest.approx(24.0)
    assert cycle_slot["slot_score"] == pytest.approx(85.0)
    assert "24个月进入24至36个月档" in cycle_slot["scoring_rule"]
    qualification_slot = next(
        slot
        for slot in epitaxy["supply.expansion_cycle_bucket"]["metric_slots"]
        if slot["slot_code"] == "qualification_or_ramp_cycle_bucket"
    )
    assert qualification_slot["value_status"] == "not_found_after_search"
