from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from tools.opportunity_lens.run18_pack_builder import build_pack
from tools.opportunity_lens.run_pack_contract import (
    public_markdown_character_count,
    validate_run_pack,
)


class Run18PackBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pack = build_pack()

    def test_stage_contract_and_three_method_structure(self) -> None:
        report = validate_run_pack(self.pack, publication_mode="stage")
        self.assertTrue(report.valid, report.as_dict())
        self.assertEqual(
            [entity["key"] for entity in self.pack["entities"]],
            [
                "industry_total_method",
                "brand_factory_method",
                "upstream_battery_method",
                "three_method_synthesis",
            ],
        )
        self.assertTrue(
            all(
                entity["entity_research_mode"] == "theory_research"
                for entity in self.pack["entities"]
            )
        )
        self.assertEqual(self.pack.get("targets", []), [])
        self.assertEqual(len(self.pack["prompt_requirements"]), 14)
        self.assertTrue(
            all(not entity.get("factor_scores") for entity in self.pack["entities"])
        )

    def test_depth_headings_and_homepage_limit(self) -> None:
        headings = (
            "### 问题",
            "### 研究方法与数据",
            "### 研究与分析",
            "### 总结",
        )
        for section in self.pack["sections"] + self.pack["entity_sections"]:
            body = section["body_markdown"]
            for heading in headings:
                self.assertEqual(body.count(heading), 1, (section.get("section_key"), heading))
        self.assertTrue(
            all(
                200 <= public_markdown_character_count(section["body_markdown"]) <= 700
                for section in self.pack["sections"]
            )
        )
        self.assertTrue(
            all(len(section["body_markdown"]) >= 1_200 for section in self.pack["entity_sections"])
        )

    def test_parallel_facts_and_unique_theory_uses(self) -> None:
        self.assertGreaterEqual(len(self.pack["data_points"]), 100)
        for entity in self.pack["entities"]:
            points = entity["research_data_points"]
            self.assertGreaterEqual(len(points), 8)
            uses = [point["research_use"] for point in points]
            self.assertEqual(len(uses), len(set(uses)))

    def test_model_freeze_hash_and_inventory_identity(self) -> None:
        model_path = Path(
            "opportunity_lens/research_outputs/20260803_nev_production_inventory_run18/"
            "nev_three_method_model_v1.json"
        )
        model = json.loads(model_path.read_text(encoding="utf-8"))
        actual_sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
        freeze = self.pack["modeling_records"][0]
        self.assertEqual(freeze["output_artifact_hash"], f"sha256:{actual_sha}")
        self.assertEqual(
            model["method_weights"],
            {"industry_total": 0.45, "brand_bottom_up": 0.30, "upstream_leading": 0.25},
        )
        for row in model["ensemble_forecast"]:
            identity = (
                row["production_10k"]["point"]
                - row["domestic_retail_10k"]["point"]
                - row["china_factory_export_10k"]["point"]
            )
            self.assertAlmostEqual(identity, row["system_inventory_flow_10k"]["point"], places=6)

    def test_public_formulas_are_standalone_and_not_corrupted(self) -> None:
        bodies = [
            section["body_markdown"]
            for section in self.pack["sections"] + self.pack["entity_sections"]
        ]
        public_text = "\n".join(bodies)
        self.assertIn(r"\widehat P_t", public_text)
        self.assertIn(r"\times", public_text)
        self.assertNotIn("\t", public_text)
        for body in bodies:
            fence_count = 0
            for line in body.splitlines():
                if "$$" in line:
                    self.assertEqual(line.strip(), "$$", line)
                    fence_count += 1
            self.assertEqual(fence_count % 2, 0)

    def test_comparison_visual_is_present(self) -> None:
        visuals = {row["block_key"]: row for row in self.pack["visuals"]}
        self.assertEqual(
            set(visuals),
            {"nev_history_forecast", "battery_vs_vehicle_index", "three_method_comparison"},
        )
        panel = visuals["three_method_comparison"]["data"]["chart"]["panels"][0]
        self.assertEqual(
            {series["label"] for series in panel["series"]},
            {"行业总量法", "品牌/工厂法", "动力电池法", "综合中值"},
        )
        combined = next(series for series in panel["series"] if series["label"] == "综合中值")
        self.assertEqual(combined["values"], [139, 159, 169])
        fallback_rows = visuals["three_method_comparison"]["print_fallback"]["rows"]
        self.assertIn("147—172（159）", fallback_rows[1][1])
        self.assertIn("140—149（145）", fallback_rows[2][-1])

    def test_required_history_brand_and_ownership_tables_are_not_stubbed(self) -> None:
        sections = {row["entity_key"]: row["body_markdown"] for row in self.pack["entity_sections"]}
        industry = sections["industry_total_method"]
        brand = sections["brand_factory_method"]
        upstream = sections["upstream_battery_method"]
        self.assertIn("国内零售 | 上险 | 中国工厂出口", industry)
        self.assertIn("厂商库存变化 | 渠道库存变化 | 生产体系库存变化", industry)
        self.assertIn("2026-07-01至2026-07-26", industry)
        self.assertIn("比亚迪 | 中国自主", brand)
        self.assertIn("特斯拉中国 | 外资独资中国生产", brand)
        self.assertNotIn("| None |", brand)
        self.assertIn("已识别外国品牌合资", brand)
        self.assertIn("中国品牌合资体系", brand)
        self.assertIn("上汽通用五菱虽然是中外合资法人", brand)
        self.assertIn("未识别尾部", brand)
        self.assertNotIn("外国品牌合资体系与尾部校准", brand)
        self.assertIn("动力电池装车量 | 新能源乘用车产量 | 来源", upstream)
        self.assertIn("不能稳定提前一个月预测整车", upstream)
        self.assertIn("0.970", upstream)
        self.assertIn("125.6万辆", upstream)
        self.assertIn("73.751", upstream)

    def test_monthly_sources_company_series_and_claim_refs_are_auditable(self) -> None:
        points = {row["data_point_key"]: row for row in self.pack["data_points"]}
        for month in (
            "2025-07",
            "2025-08",
            "2025-09",
            "2025-10",
            "2025-11",
            "2025-12",
            "2026-01",
            "2026-02",
            "2026-03",
            "2026-04",
            "2026-05",
            "2026-06",
        ):
            expected_ref = f"w-industry-cpca_{month.replace('-', '_')}"
            for metric in ("production", "wholesale", "retail", "export"):
                self.assertEqual(
                    points[f"industry-{month}-{metric}"]["source_ref"], expected_ref
                )

        brand_points = [
            row for row in self.pack["data_points"] if row["entity_key"] == "brand_factory_method"
        ]
        self.assertEqual(len([row for row in brand_points if row["data_point_key"].endswith("-june-base")]), 15)
        forecast_points = [row for row in brand_points if row.get("observations")]
        self.assertEqual(len(forecast_points), 15 * 4)
        for row in forecast_points:
            self.assertEqual(len(row["observations"]), 3)
            self.assertIn("model-run18-three-method", row["underlying_source_refs"])
            self.assertGreaterEqual(len(row["underlying_source_refs"]), 3)

        claims = {row["claim_key"]: row for row in self.pack["claims"]}
        self.assertEqual(claims["c05"]["source_ref"], "w-upstream-s18")
        self.assertEqual(claims["c06"]["source_ref"], "model-run18-three-method")

        sources = {row["ref"]: row for row in self.pack["sources"]}
        self.assertEqual(sources["w-industry-cpca_2026_06"]["publish_date"], "2026-07-14")
        self.assertEqual(
            sources["w-industry-cada_dealer_inventory_june"]["publish_date"],
            "2026-07-10",
        )

    def test_public_numbers_match_frozen_bridges(self) -> None:
        sections = {row["entity_key"]: row["body_markdown"] for row in self.pack["entity_sections"]}
        industry = sections["industry_total_method"]
        brand = sections["brand_factory_method"]
        synthesis = sections["three_method_synthesis"]
        self.assertIn("133.6万辆，再上调4.4万辆", industry)
        self.assertIn("少约6.3万辆", brand)
        self.assertIn("净增约5.7万辆", brand)
        self.assertIn("净增约9.8万辆", brand)
        self.assertIn("125—156", synthesis)
        self.assertIn("145—178", synthesis)
        self.assertIn("150—190", synthesis)
        self.assertIn("147—172 （159）", synthesis)
        self.assertIn("冻结模型以两位小数保存", synthesis)
        for stale in ("127—156", "156—191", "三条相互独立", "外国品牌合资体系与尾部校准"):
            self.assertNotIn(stale, "\n".join(sections.values()))


if __name__ == "__main__":
    unittest.main()
