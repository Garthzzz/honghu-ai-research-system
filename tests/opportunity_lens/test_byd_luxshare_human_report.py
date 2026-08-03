from __future__ import annotations

import json
import hashlib
import re
import unittest
from pathlib import Path

from tools.opportunity_lens.byd_luxshare_human_report import (
    PUBLIC_FORBIDDEN_FRAGMENTS,
    audit_human_public_content,
)
from tools.opportunity_lens.public_content_quality_audit import run_audit
from tools.opportunity_lens.read_models import _value_display


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260718_byd_luxshare_optical_module_competition_deep_run"
)
PACK_PATH = OUTPUT_DIR / "run_pack.json"
REPORT_PATH = OUTPUT_DIR / "final_report.md"


class BydLuxshareHumanReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pack = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        cls.report = REPORT_PATH.read_text(encoding="utf-8")

    def test_public_composition_is_four_sections_and_nine_linked_entity_answers(self):
        self.assertEqual(len(self.pack["sections"]), 4)
        self.assertEqual(len(self.pack["entity_sections"]), 9)
        self.assertGreaterEqual(
            min(len(row["body_markdown"]) for row in self.pack["sections"]),
            1400,
        )
        self.assertGreaterEqual(
            min(len(row["body_markdown"]) for row in self.pack["entity_sections"]),
            2200,
        )
        metrics = audit_human_public_content(
            self.pack["sections"], self.pack["entity_sections"]
        )
        self.assertEqual(metrics["human_public_forbidden_fragment_count"], 0)
        self.assertEqual(metrics["human_public_duplicate_long_paragraph_count"], 0)

    def test_probability_and_finance_tables_are_capped_and_purpose_specific(self):
        table_counts = self.pack["build_metrics"][
            "human_public_table_count_by_section"
        ]
        self.assertEqual(table_counts["core_answers"], 1)
        self.assertEqual(table_counts["financial_method_and_results"], 2)
        self.assertEqual(table_counts["entity_answer_recruitment_patent_capacity_audit"], 1)
        self.assertEqual(self.pack["build_metrics"]["human_public_table_count"], 5)
        self.assertEqual(len(self.pack["visuals"]), 1)
        self.assertEqual(
            self.pack["visuals"][0]["block_key"], "market_supply_demand_visual"
        )

    def test_market_units_are_converted_from_usd_bn_to_hundred_million_usd(self):
        # 模型字段单位是十亿美元；中文“亿美元”必须乘以 10，不能只改单位标签。
        self.assertIn("84.6亿美元", self.report)
        self.assertIn("253.3亿美元", self.report)
        self.assertNotIn("8.46亿美元", self.report)
        self.assertNotIn("25.33亿美元", self.report)
        self.assertIn("3,300万个", self.report)
        self.assertIn("1.28亿个", self.report)

    def test_public_report_exposes_material_model_sensitivity_without_machine_terms(self):
        self.assertIn("比亚迪三年使用6%、13%和32%，代表值约17%", self.report)
        self.assertIn("比亚迪约17%和35%", self.report)
        self.assertNotIn("比亚迪三年使用6%、12%和22%", self.report)
        self.assertNotIn("比亚迪约13%和31%", self.report)
        self.assertIn("三年结果约在47%—57%之间", self.report)
        self.assertIn("五年约在68%—82%之间", self.report)
        self.assertIn("需求偏快与偏慢对应的供给/需求约为1.01倍和1.73倍", self.report)
        self.assertIn("供给爬坡偏慢与偏快对应约1.14—1.65倍", self.report)
        self.assertIn("不能给出可信的经验概率", self.report)
        self.assertIn("放宽为年化收入5亿元", self.report)
        self.assertIn("三年63%、五年83%", self.report)
        self.assertIn("提高到年化收入20亿元", self.report)
        self.assertIn("三年40%、五年61%", self.report)
        self.assertIn("三年结果进一步降至约38%", self.report)

    def test_public_event_definition_and_financial_scenario_match_the_model(self):
        self.assertIn("年化相关收入达到10亿元", self.report)
        self.assertIn("全球市场份额达到1%", self.report)
        self.assertIn("中国市场份额达到5%", self.report)
        self.assertIn("只有一家新进入者进入全球头部客户、传统可插拔仍占主导", self.report)
        self.assertNotIn("| 至少一家进入全球头部客户 | 传统可插拔", self.report)
        self.assertIn("受影响收入占比每增加10个百分点", self.report)
        self.assertIn("约1.17、2.11和4.59个百分点", self.report)
        self.assertIn("新易盛约1.37、2.39和5.52个百分点", self.report)
        self.assertIn("毛利率下降的72%传导到净利率", self.report)
        self.assertIn("中际旭创的三项比例从2026年的44% / 29% / 18%逐步降至2031年的39% / 24% / 14%", self.report)
        self.assertIn("新易盛从47% / 37% / 22%降至38% / 25% / 13%", self.report)
        self.assertIn("传统可插拔、显著LPO/LRO迁移和CPO增量风险约按51%、38%和11%加权", self.report)
        self.assertIn("不是市场份额", self.report)
        self.assertIn("中际旭创到2031年两项均约0.55%", self.report)
        self.assertIn("新易盛均约0.65%", self.report)
        self.assertIn("公开资料不能拆出分业务现金转化率", self.report)
        self.assertIn("不是两笔独立估计恰好相等", self.report)
        self.assertIn("不是公司披露", self.report)
        self.assertNotIn("不是对这四行直接取平均", self.report)
        self.assertIn("1,701亿元人民币（约250.97亿美元）", self.report)
        self.assertIn("3,266亿元人民币（约481.94亿美元）", self.report)
        self.assertIn("988亿元人民币（约145.83亿美元）", self.report)
        self.assertIn("1,634亿元人民币（约241.11亿美元）", self.report)
        self.assertNotIn("受影响收入比例敏感性", self.report)
        self.assertNotIn("概率加权结果暂把进入者进度与架构迁移", self.report)
        self.assertNotIn("（对照值）", self.report)
        self.assertNotIn("较对照低0%", self.report)

        self.assertIn("2025年简单自由现金流等于经营现金流减去购建固定资产", self.report)
        self.assertIn("2031年情景现金流则从正常化现金流中再扣除防守性扩产和新增营运资本", self.report)
        self.assertIn("50%、75%和100%", self.report)
        self.assertIn("5.87% / 10.57% / 22.93%", self.report)
        self.assertIn("8.81% / 15.86% / 34.39%", self.report)
        self.assertIn("11.74% / 21.14% / 45.86%", self.report)
        self.assertIn("6.83% / 11.92% / 27.58%", self.report)
        self.assertIn("10.25% / 17.89% / 41.37%", self.report)
        self.assertIn("13.66% / 23.85% / 55.16%", self.report)

        model_inputs = json.loads(
            (OUTPUT_DIR / "model_inputs.json").read_text(encoding="utf-8")
        )
        for company_key in ("innolight", "eoptolink"):
            self.assertEqual(
                model_inputs["financial"]["companies"][company_key][
                    "high_speed_revenue_exposure_share"
                ],
                1.0,
            )

    def test_all_target_cny_amounts_render_with_same_snapshot_usd_equivalent(self):
        cny_rows = [
            row
            for target in self.pack["entity_investment_targets"]
            for row in target["target_data_points"]
            if row.get("unit") == "亿元人民币"
        ]
        self.assertEqual(len(cny_rows), 20)
        for row in cny_rows:
            display = _value_display(row)
            self.assertIn("亿元人民币（约", display)
            self.assertTrue(display.endswith("亿美元）"), display)

    def test_contract_required_geography_and_damage_probabilities_are_human_readable(self):
        self.assertIn("地域差异比总进入概率更能说明风险先从哪里出现", self.report)
        self.assertIn("比亚迪进入中国客户体系的判断约为三年12%、五年27%", self.report)
        self.assertIn("进入全球头部客户约为三年1%、五年7%", self.report)
        self.assertIn("立讯对应约为中国三年37%、五年55%", self.report)
        self.assertIn("全球三年9%、五年27%", self.report)
        self.assertIn("路径约为三年33%、五年35%", self.report)
        self.assertIn("中国与全球数字可以重叠", self.report)

        self.assertIn(
            "### 至少一家进入后，竞争和长期盈利会恶化到什么程度",
            self.report,
        )
        for value in (
            "58.43%",
            "31.74%",
            "9.83%",
            "42.02%",
            "38.90%",
            "19.08%",
            "65.60%",
            "77.38%",
            "47.64%",
            "56.20%",
        ):
            self.assertIn(value, self.report)
        self.assertIn("2029—2031年平均净利润和情景现金流", self.report)
        self.assertIn("低至少15%", self.report)
        self.assertIn("2031年正常化终值低至少20%", self.report)
        self.assertIn("不是行业历史发生率", self.report)
        self.assertIn("再用各路径的进入概率加权并重新归一", self.report)
        self.assertIn("不是从下文财务结果反算的分类", self.report)
        self.assertIn("15%和20%阈值是另一项独立计算", self.report)
        self.assertIn("全公司收入100%受影响的压力上限", self.report)
        self.assertIn("2031年收入：参考→进入后均值", self.report)
        self.assertIn("3,266.02 → 2,778.12", self.report)
        self.assertIn("783.84 → 575.70", self.report)
        self.assertIn("457.24 → 198.74", self.report)
        self.assertIn("5,232.86 → 3,409.11", self.report)
        self.assertIn("1,633.96 → 1,349.98", self.report)
        self.assertIn("408.49 → 286.18", self.report)
        self.assertIn("212.41 → 68.25", self.report)
        self.assertIn("2,430.91 → 1,423.10", self.report)
        self.assertIn("排除后重新加权", self.report)
        self.assertNotIn("专家压力带", self.report)

        model_inputs = json.loads(
            (OUTPUT_DIR / "model_inputs.json").read_text(encoding="utf-8")
        )
        provenance = {
            row["input"]: row for row in model_inputs["input_provenance"]
        }
        severity_input = provenance["conditional_competition_severity_weights"]
        self.assertEqual(
            severity_input["status"],
            "structured_expert_assumption_not_external_fact",
        )
        self.assertFalse(severity_input["external_fact"])
        self.assertIn("明显权重等于1减温和权重再减严重权重", severity_input["note"])
        self.assertIn("未由历史频率或财务阈值校准", severity_input["note"])

        source_lookup = {row["ref"]: row for row in self.pack["sources"]}
        for source_ref, filename in (
            ("MODEL-INPUTS", "model_inputs.json"),
            ("MODEL-WORKPAPER", "model_outputs.json"),
        ):
            artifact_hash = hashlib.sha256((OUTPUT_DIR / filename).read_bytes()).hexdigest()
            self.assertEqual(
                source_lookup[source_ref]["document_sha256"],
                artifact_hash,
            )

    def test_rendered_report_has_human_title_and_no_old_shared_appendix(self):
        self.assertIn(
            "# 比亚迪与立讯进军光模块：竞争与盈利风险",
            self.report,
        )
        self.assertEqual(
            self.pack["display_title"], "比亚迪与立讯进军光模块：竞争与盈利风险"
        )
        self.assertLessEqual(len(self.pack["display_title"]), 24)
        self.assertNotIn("附录共用方法与财务边界", self.report)
        self.assertIn("| 来源标题 | 发布方 | 发布/事件日期 |", self.report)
        self.assertNotIn("| 来源ID |", self.report)
        self.assertNotIn("| MODEL-WORKPAPER ", self.report)
        for token in (
            "current_at_fetch",
            "current_at_access",
            "2026-spring",
            "2025-campus-cycle",
            "2026-03-17/2026-03-19",
        ):
            self.assertNotIn(token, self.report)
        for fragment in PUBLIC_FORBIDDEN_FRAGMENTS:
            self.assertNotIn(fragment, self.report)

    def test_every_inline_citation_resolves_to_a_pack_source(self):
        source_refs = {source["ref"] for source in self.pack["sources"]}
        cited = set(
            re.findall(r"\^src:source_ref:([A-Za-z0-9_.-]+)", self.report)
        )
        self.assertTrue(cited)
        self.assertFalse(cited - source_refs)

    def test_new_search_leads_remain_downgraded_and_patent_boundaries_are_explicit(self):
        source_lookup = {row["ref"]: row for row in self.pack["sources"]}
        shared_call_key = "event:byd-electronic-2025h1-results-briefing-unpublished"
        for source_ref in (
            "BYD-LEAD-FIRSTSH-20250901",
            "BYD-LEAD-CMBI-20250902",
            "BYD-LEAD-CINDA-20250905",
            "BYD-LEAD-CMBI-20260206",
        ):
            source = source_lookup[source_ref]
            self.assertEqual(source["source_tier"], "C")
            self.assertEqual(source["source_review_status"], "weak_source_only")
            self.assertEqual(source["policy_evidence_role"], "reference_only")
            self.assertEqual(source["independence_key"], shared_call_key)
            self.assertEqual(source["origin_type"], "secondary_research_relay")
            self.assertEqual(source["public_source_origin_class"], "sell_side_media")
            self.assertEqual(source["intake_source_tier"], "Tier 3")
        for source_ref in (
            "BYD-LEAD-ABSM-20260718",
            "BYD-LEAD-TGB-20260718",
        ):
            source = source_lookup[source_ref]
            self.assertEqual(source["source_tier"], "D")
            self.assertEqual(source["policy_evidence_role"], "reference_only")
            self.assertEqual(
                source["independence_key"],
                "narrative:byd-optical-module-july-2026",
            )

        applicant_record = source_lookup["BYD-PAT-CN121012567A"]
        self.assertIn("济南比亚迪半导体", applicant_record["excerpt"])
        self.assertIn("应用仍是车辆", applicant_record["excerpt_zh"])
        self.assertIn("不能写成已向英伟达或海外云客户批量交付", self.report)
        self.assertIn("三份报告都指向同一次未公开的管理层交流，因此只能算一个底层信息源", self.report)
        self.assertIn("比亚迪股份与济南比亚迪半导体的连续申请", self.report)
        self.assertNotIn("尚无公开可核实的800G以上模块", self.report)

        claim_lookup = {row["claim_id"]: row for row in self.pack["claims"]}
        self.assertEqual(claim_lookup["BYD-C14"]["policy_evidence_role"], "reference_only")
        self.assertFalse(claim_lookup["BYD-C14"]["probability_update_links"])
        self.assertEqual(claim_lookup["BYD-C14"]["counts"]["support_group_count"], 1)
        self.assertEqual(claim_lookup["BYD-C14"]["counts"]["counter_group_count"], 3)
        self.assertEqual(claim_lookup["BYD-C15"]["policy_evidence_role"], "reference_only")
        self.assertFalse(claim_lookup["BYD-C15"]["probability_update_links"])
        self.assertEqual(
            claim_lookup["BYD-C15"]["supporting_source_refs"],
            ["BYD-LEAD-ABSM-20260718", "BYD-LEAD-TGB-20260718"],
        )
        self.assertEqual(
            claim_lookup["BYD-C15"]["counter_source_refs"],
            ["BYD-LEAD-IDCE-2026", "BYD-S18", "BYD-S01"],
        )
        self.assertTrue(claim_lookup["BYD-C13"]["probability_update_links"])
        self.assertEqual(self.pack["build_metrics"]["core_independent_source_group_count"], 32)
        patent_source = source_lookup["BYD-PAT-CN122362593A"]
        self.assertEqual(patent_source["origin_type"], "registry_mirror")
        self.assertEqual(
            patent_source["public_source_origin_class"],
            "regulatory_government_standard",
        )
        self.assertTrue(patent_source["local_locator"])
        for source_ref in (
            "BYD-LEAD-FIRSTSH-20250901",
            "BYD-LEAD-CMBI-20250902",
            "BYD-LEAD-CINDA-20250905",
        ):
            self.assertTrue(source_lookup[source_ref]["local_locator"])
        for process_term in ("旧稿", "本轮扩展检索", "比亚迪电子已经披露过"):
            self.assertNotIn(process_term, self.report)

    def test_independent_public_content_audit_passes_without_exemptions(self):
        result = run_audit(
            run_pack_path=PACK_PATH,
            report_path=REPORT_PATH,
            profile="byd_luxshare",
        )
        self.assertEqual(result["status"], "PASS", result["issues"])
        self.assertEqual(result["summary"]["errors"], 0)
        self.assertEqual(result["summary"]["warnings"], 0)


if __name__ == "__main__":
    unittest.main()
