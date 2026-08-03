from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from tools.opportunity_lens.run16_pack_builder import (
    EXECUTABLE_MODEL_SOURCE_REF,
    EXECUTABLE_PORTFOLIO_PATH,
    INDEPENDENT_MODEL_PATH,
    MOJIBAKE_MARKERS,
    _file_sha256,
    _load_company_map,
    _public_draft,
    build_pack,
)
from tools.opportunity_lens.run16_executable_portfolio_freeze import (
    validate_executable_artifact,
)
from tools.opportunity_lens.run16_company_causal_research import (
    COMPANY_CAUSAL_RESEARCH,
)
from tools.opportunity_lens.run16_application_commercial_research import (
    application_rows,
    calculation_audit,
)
from tools.opportunity_lens.run16_application_industry_research import (
    SUBSECTOR_RESEARCH,
    expanded_company_rows,
)
from tools.opportunity_lens.run16_source_catalog import evidence_summary
from tools.opportunity_lens.run_pack_contract import (
    public_markdown_character_count,
    validate_run_pack,
)


class Run16PackBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pack = build_pack()

    def test_parallel_evidence_is_not_time_series_padding(self) -> None:
        self.assertEqual(
            evidence_summary(),
            {
                "source_count": 136,
                "independent_source_group_count": 127,
                "parallel_data_point_count": 224,
                "report_source_count": 13,
                "web_source_count": 123,
            },
        )

    def test_stage_pack_contract_and_quality_floors(self) -> None:
        report = validate_run_pack(self.pack, publication_mode="stage")
        self.assertTrue(report.valid, report.as_dict())
        self.assertEqual(len(self.pack["prompt_requirements"]), 23)
        self.assertEqual(self.pack["review_records"], [])
        self.assertLessEqual(
            sum(
                public_markdown_character_count(row["body_markdown"])
                for row in self.pack["sections"]
            ),
            15_000,
        )
        self.assertTrue(
            all(
                200 <= public_markdown_character_count(row["body_markdown"]) <= 600
                for row in self.pack["sections"]
            )
        )
        self.assertTrue(
            all(
                len(row["body_markdown"]) >= 1_200
                for row in self.pack["entity_sections"]
            )
        )
        self.assertEqual(len(self.pack["entities"]), 9)
        self.assertEqual(self.pack["homepage_section_max_characters"], 600)
        self.assertEqual(
            {row["entity_type"] for row in self.pack["entities"]},
            {"theme"},
        )

    def test_same_microsoft_disclosure_uses_one_independence_key(self) -> None:
        sources = {row["ref"]: row for row in self.pack["sources"]}
        self.assertEqual(
            sources["app-w01"]["independence_key"],
            sources["chain-fc-w012"]["independence_key"],
        )

    def test_contract_rejects_entity_enums_that_live_db_cannot_store(self) -> None:
        invalid = deepcopy(self.pack)
        invalid["entities"][0]["entity_type"] = "research_theme"
        report = validate_run_pack(invalid, publication_mode="stage")
        self.assertFalse(report.valid)
        self.assertIn("entity_type_enum", {issue.code for issue in report.issues})

    def test_public_draft_has_no_common_mojibake(self) -> None:
        draft = _public_draft(self.pack)
        for marker in MOJIBAKE_MARKERS:
            self.assertNotIn(marker, draft)
        self.assertIn("AI应用与全产业链组合研究", draft)
        self.assertIn("研究方法与数据", draft)
        self.assertNotIn("canonical", draft)
        self.assertNotIn("intake", draft)
        self.assertIn("九个应用细分行业", draft)
        self.assertIn("应用组合持有[合合信息](/company/669)16.98%", draft)
        self.assertNotIn("## 摘要", draft)
        self.assertIn(
            "## 哪些AI方向和公司能把需求转成现金利润，当前怎样配置？",
            draft,
        )
        self.assertIn(
            "## AI应用与全产业链哪些方向更值得配置，优先公司是谁？",
            draft,
        )
        self.assertNotRegex(draft, r"\bS[0-5](?:_candidate)?\b")
        self.assertIn(
            "/opportunity-lens/run/16/entity-name/AI应用：公司优选与组合", draft
        )
        self.assertIn(
            "/opportunity-lens/run/16/entity-name/AI全产业链：公司优选与组合", draft
        )
        self.assertNotIn("AI应用商业化与付费验证", draft)
        self.assertNotIn("AI应用公司经营与估值", draft)
        self.assertNotIn("通用AI加速器", draft)
        entity_text = "\n".join(
            section["body_markdown"] for section in self.pack["entity_sections"]
        )
        self.assertIn("全链细分排名", entity_text)
        self.assertIn("外资数据中心审批风险报告", entity_text)
        self.assertIn("AI服务器电容深度报告", entity_text)

    def test_entities_follow_operating_to_valuation_to_portfolio_logic(self) -> None:
        self.assertEqual(
            [entity["key"] for entity in self.pack["entities"]],
            [
                "ai_application_subsectors",
                "ai_application_companies",
                "ai_application_portfolios",
                "ai_chain_architecture",
                "ai_compute_semiconductor",
                "ai_systems_interconnect_pcb",
                "ai_data_center_physical",
                "ai_full_chain_portfolios",
                "key_risks",
            ],
        )

    def test_complex_formulas_are_standalone_display_blocks(self) -> None:
        bodies = [
            section["body_markdown"]
            for section in self.pack["sections"] + self.pack["entity_sections"]
        ]
        for body in bodies:
            formula_fences = 0
            for line in body.splitlines():
                if "$$" not in line:
                    continue
                self.assertEqual(line.strip(), "$$", line)
                formula_fences += 1
            self.assertEqual(formula_fences % 2, 0)

        public_text = "\n".join(bodies)
        for internal_token in (
            r"\operatorname",
            r"\mathcal",
            r"\qquad",
            "CapDirectionSingleNameCash",
            "A_i=",
            "S_i=",
            "w_i^{raw}",
            "Revenue_",
            "Compute_",
            "FCF_",
        ):
            self.assertNotIn(internal_token, public_text)

    def test_application_companies_have_commercial_and_financial_chain(self) -> None:
        entity_text = "\n".join(
            section["body_markdown"]
            for section in self.pack["entity_sections"]
            if section["entity_key"] == "ai_application_companies"
        )
        self.assertGreaterEqual(len(application_rows()), 10)
        for row in application_rows():
            self.assertIn(row["company"], entity_text)
            self.assertIn(row["buyer_and_evidence"], entity_text)
            self.assertIn(row["buyer_value_math"], entity_text)
            self.assertIn(row["market_and_model_test"], entity_text)
            self.assertIn(row["investment_view"], entity_text)
        for required_phrase in (
            "谁付钱、已经验证到哪里",
            "客户为什么愿意付钱",
            "可复制空间与财务模型检验",
            "估值与行动条件",
            "合同、启动、上线、验收、收入和回款",
        ):
            self.assertIn(required_phrase, entity_text)

    def test_application_valuation_prose_matches_current_frozen_model(self) -> None:
        entity_text = next(
            section["body_markdown"]
            for section in self.pack["entity_sections"]
            if section["entity_key"] == "ai_application_companies"
        )
        for stale_number in (
            "888.64",
            "1,166.34",
            "1,192.80",
            "1,533.60",
            "656.40",
            "902.55",
            "70.20—93.60",
            "305.60—420.20",
        ):
            self.assertNotIn(stale_number, entity_text)
        for current_range in (
            "557.48—836.35亿元",
            "179.43—269.11亿元",
            "541.02—811.53亿元",
            "664.11—996.25亿元",
            "27.84—41.76亿元",
            "41.47—62.21亿元",
        ):
            self.assertIn(current_range, entity_text)
        self.assertIn("应用侧只配置[合合信息]", entity_text)
        self.assertIn("均高于独立核心区间，当前回避", entity_text)

    def test_public_non_a_share_company_headings_use_canonical_links(self) -> None:
        entity_text = next(
            section["body_markdown"]
            for section in self.pack["entity_sections"]
            if section["entity_key"] == "ai_application_companies"
        )
        for company, company_id in (
            ("快手", 101),
            ("百度", 87),
            ("阿里巴巴", 33),
            ("腾讯控股", 697),
        ):
            self.assertRegex(
                entity_text,
                rf"##### 公司｜\[{company}\]\(/company/{company_id}\)｜",
            )

    def test_application_subsectors_and_company_groups_have_required_depth(self) -> None:
        industry_text = next(
            section["body_markdown"]
            for section in self.pack["entity_sections"]
            if section["entity_key"] == "ai_application_subsectors"
        )
        company_text = next(
            section["body_markdown"]
            for section in self.pack["entity_sections"]
            if section["entity_key"] == "ai_application_companies"
        )
        self.assertEqual(len(SUBSECTOR_RESEARCH), 9)
        self.assertEqual(industry_text.count("#### 细分行业｜"), 9)
        self.assertEqual(company_text.count("#### 公司组｜"), 9)
        self.assertEqual(company_text.count("##### 公司｜"), 37)
        self.assertGreaterEqual(len(expanded_company_rows()), 26)
        for phrase in (
            "市场规模与转化阶段",
            "提供方、产品和竞争格局",
            "购买方、合同与客户价值",
            "当前能力、未来边界与财务传导",
        ):
            self.assertIn(phrase, industry_text)

    def test_application_customer_value_calculations_use_correct_units(self) -> None:
        audit = calculation_audit()
        expected = {
            "wps_1m_seat_advanced_increment_100m_cny": 2.0,
            "wps_1m_seat_flagship_increment_100m_cny": 4.0,
            "digiwin_low_incremental_profit_100m_cny": 0.280245,
            "digiwin_high_incremental_profit_100m_cny": 0.399245,
            "iflytek_teacher_value_low_100m_cny": 0.152,
            "iflytek_teacher_value_high_100m_cny": 0.304,
            "sangfor_contract_review_hours": 9_833.333333333334,
            "sangfor_low_labor_value_10k_cny": 98.33333333333334,
            "sangfor_high_labor_value_10k_cny": 196.66666666666669,
            "yonyou_low_incremental_profit_100m_cny": 1.82865,
            "yonyou_high_incremental_profit_100m_cny": 3.08115,
            "hundsun_20_client_low_revenue_100m_cny": 0.2,
            "hundsun_20_client_high_revenue_100m_cny": 0.6,
            "baosight_low_scrap_value_100m_cny": 0.075,
            "baosight_high_scrap_value_100m_cny": 0.1,
            "glodon_project_value_low_100m_cny": 2.5,
            "glodon_project_value_high_100m_cny": 5.0,
            "wondershare_low_breakeven_revenue_100m_cny": 1.3,
            "wondershare_high_breakeven_revenue_100m_cny": 1.9,
        }
        self.assertEqual(set(audit), set(expected))
        for key, value in expected.items():
            self.assertAlmostEqual(audit[key], value, places=9, msg=key)

    def test_company_causal_research_is_public_and_source_backed(self) -> None:
        entity_text = "\n".join(
            section["body_markdown"] for section in self.pack["entity_sections"]
        )
        source_refs = {source["ref"] for source in self.pack["sources"]}
        company_count = 0
        for rows in COMPANY_CAUSAL_RESEARCH.values():
            for row in rows:
                company_count += 1
                self.assertIn(row["company"], entity_text)
                self.assertTrue(set(row["refs"]).issubset(source_refs))
                self.assertIn(row["status"], {"三年财务模型", "经营与估值对照"})
        self.assertEqual(company_count, 29)

    def test_portfolio_entity_explains_each_final_weight(self) -> None:
        portfolio_text = "\n".join(
            section["body_markdown"]
            for section in self.pack["entity_sections"]
            if "portfolios" in section["entity_key"]
        )
        self.assertIn("公司判断怎样变成最终权重", portfolio_text)
        self.assertIn("候选风险权重", portfolio_text)
        self.assertIn("当前价格与现金流门槛", portfolio_text)
        self.assertIn("可执行权重", portfolio_text)
        self.assertIn("未通过门槛的股票权重原额转入现金", portfolio_text)

    def test_executable_targets_do_not_hold_currently_rejected_names(self) -> None:
        rejected = {
            "AI应用": {"金山办公", "同花顺", "科大讯飞", "鼎捷数智", "深信服"},
            "AI全产业链": {
                "北方华创", "澜起科技", "海光信息", "沪电股份",
                "英维克", "润泽科技", "中恒电气",
            },
        }
        expected = {
            "AI应用": {"合合信息"},
            "AI全产业链": {"中际旭创", "立讯精密", "工业富联", "生益科技", "汇川技术"},
        }
        for target in self.pack["entity_investment_targets"]:
            scope = "AI应用" if target["target_name"].startswith("AI应用") else "AI全产业链"
            profile = target["target_profile_markdown"]
            exposure = target["exposure_rationale"]
            for name in rejected[scope]:
                self.assertNotIn(name, exposure, f"{target['target_name']} 仍持有 {name}")
            self.assertTrue(
                any(name in exposure for name in expected[scope]),
                f"{target['target_name']} 没有任何通过当前门槛的股票",
            )
            self.assertIn("现金", profile)

    def test_executable_portfolios_are_bound_to_a_separate_frozen_artifact(self) -> None:
        model = json.loads(
            INDEPENDENT_MODEL_PATH.read_text(encoding="utf-8")
        )
        executable = json.loads(
            EXECUTABLE_PORTFOLIO_PATH.read_text(encoding="utf-8")
        )
        validate_executable_artifact(executable, model, INDEPENDENT_MODEL_PATH)
        self.assertEqual(
            executable["input_independent_model"]["file_sha256"],
            _file_sha256(INDEPENDENT_MODEL_PATH),
        )
        self.assertEqual(executable["sanity"]["verdict"], "GREEN")
        self.assertEqual(len(executable["portfolios"]), 6)
        sources = {row["ref"]: row for row in self.pack["sources"]}
        self.assertIn(EXECUTABLE_MODEL_SOURCE_REF, sources)
        self.assertEqual(
            sources[EXECUTABLE_MODEL_SOURCE_REF]["local_path"],
            "opportunity_lens/research_outputs/20260801_ai_app_full_chain_portfolio_run16/financial_artifacts/run16_current_executable_portfolios.json",
        )
        scenario_record = next(
            row
            for row in self.pack["modeling_records"]
            if row["skill_name"] == "probability_scenario_modeling"
        )
        self.assertEqual(
            scenario_record["output_artifact_hash"],
            _file_sha256(EXECUTABLE_PORTFOLIO_PATH),
        )

    def test_single_stock_portfolios_do_not_store_zero_pair_correlation(self) -> None:
        application_targets = [
            row
            for row in self.pack["entity_investment_targets"]
            if row["target_name"].startswith("AI应用")
        ]
        self.assertEqual(len(application_targets), 3)
        for target in application_targets:
            metrics = {
                row["metric_name"]: row
                for row in target["target_data_points"]
            }
            self.assertNotIn("最高已观测相关性", metrics)
            self.assertIn("单一股票仓位没有两两相关性", target["target_deep_research_markdown"])
            for row in target["target_data_points"]:
                self.assertIn("市场估值快照截至2026-07-30", row["period"])

    def test_run16_python_sources_have_no_common_mojibake(self) -> None:
        paths = (
            Path("tools/opportunity_lens/run16_pack_builder.py"),
            Path("tools/opportunity_lens/run16_executable_portfolio_freeze.py"),
            Path("tools/opportunity_lens/run16_source_catalog.py"),
            Path("tests/opportunity_lens/test_run16_pack_builder.py"),
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for marker in MOJIBAKE_MARKERS:
                self.assertNotIn(marker, text, f"{path} 存在疑似乱码")

    def test_first_company_mention_in_each_paragraph_is_linked(self) -> None:
        company_map = _load_company_map()
        for section in self.pack["sections"] + self.pack["entity_sections"]:
            for paragraph in section["body_markdown"].split("\n\n"):
                stripped = paragraph.lstrip()
                if not stripped or stripped.startswith(("#", "|", "```")):
                    continue
                for name, company in company_map.items():
                    if name not in paragraph:
                        continue
                    self.assertIn(
                        f"[{name}](/company/{company['company_id']})",
                        paragraph,
                        f"{section['section_key']} 段落未链接 {name}",
                    )

    def test_first_company_mention_in_each_table_is_linked(self) -> None:
        company_map = _load_company_map()
        for section in self.pack["sections"] + self.pack["entity_sections"]:
            table_lines = [
                line for line in section["body_markdown"].splitlines()
                if line.startswith("|") and not line.startswith("|---")
            ]
            table_text = "\n".join(table_lines)
            for name, company in company_map.items():
                if name not in table_text:
                    continue
                self.assertIn(
                    f"[{name}](/company/{company['company_id']})",
                    table_text,
                    f"{section['section_key']} 表格未链接 {name}",
                )

    def test_theory_profiles_are_not_copied_public_sections(self) -> None:
        limitations = set()
        for entity in self.pack["entities"]:
            if entity.get("entity_research_mode") != "theory_research":
                continue
            profile = entity["research_profile"]
            self.assertNotEqual(
                profile["methodology_note"],
                profile["literature_review_markdown"],
            )
            self.assertNotEqual(
                profile["analysis_markdown"],
                profile["answer_markdown"],
            )
            limitations.add(profile["limitations_markdown"])
        self.assertEqual(len(limitations), 7)


if __name__ == "__main__":
    unittest.main()
