from __future__ import annotations

from tools.opportunity_lens.ab_readonly import ab_row_counts
from tools.opportunity_lens.evidence_resolver import resolve
from tools.opportunity_lens.display_annotations import chinese_translation, source_original_text
from tools.opportunity_lens.validators import ValidationError

from helpers import FixtureDBTestCase
from tools.opportunity_lens.db import connect


class EvidenceResolverTests(FixtureDBTestCase):
    def test_explicit_chinese_translation_is_extracted_and_bilingual_title_needs_no_placeholder(self):
        self.assertEqual(
            chinese_translation(
                "The report shows strong demand. 中文译意：报告显示需求仍然强劲。",
                "en",
            ),
            "报告显示需求仍然强劲。",
        )
        self.assertIsNone(
            chinese_translation(
                "BofA survey 2026年6月：全球半导体被多数受访者视为拥挤交易",
                "en",
            )
        )
        self.assertEqual(
            source_original_text(
                "The report shows strong demand. 中文译意：报告显示需求仍然强劲。"
            ),
            "The report shows strong demand.",
        )
    def test_opp_resolver(self):
        conn = connect(self.db_path, readonly=True)
        try:
            source = resolve("opp://source/1", conn=conn)
            self.assertTrue(source["found"])
            self.assertEqual(source["record"]["source_tier"], "A")
            self.assertIn("human_explanation", source)
            slot = resolve("opp://metric_slot/1", conn=conn)
            self.assertEqual(slot["record"]["metric_slot_status"], "accepted")
            intake = resolve("opp://intake_contract/1", conn=conn)
            self.assertEqual(intake["record"]["research_question"], "合成 HBM 载板供需失衡扫描")
            early = resolve("opp://early_signal/1", conn=conn)
            self.assertEqual(early["record"]["core_score_changed_by_overlay"], 0)
        finally:
            conn.close()

    def test_bad_uri_is_structured_validation_error(self):
        with self.assertRaises(ValidationError):
            resolve("opp://secret/1")

    def test_ab_resolver_is_read_only(self):
        before = ab_row_counts()
        result = resolve("ab://research.source/1")
        after = ab_row_counts()
        self.assertEqual(before, after)
        self.assertEqual(result["scheme"], "ab")

    def test_ab_data_point_alias_has_human_explanation(self):
        result = resolve("ab://research.data_point/11115")
        self.assertEqual(result["scheme"], "ab")
        self.assertEqual(result["canonical_object_type"], "research.industry_data_point")
        self.assertTrue(result["found"])
        self.assertIn("human_explanation", result)
        self.assertIn("数据点", result["human_explanation"]["headline"])
        self.assertIn("linked_source", result)
        self.assertTrue(result["deep_link"].startswith("/source/"))
        explanation_text = " ".join(result["human_explanation"]["plain_steps"])
        self.assertNotIn("source_id", explanation_text)
        self.assertNotIn("opp://", explanation_text)
        self.assertNotIn("file_path", explanation_text)

    def test_external_url_resolves_to_opportunity_source(self):
        conn = connect(self.db_path, readonly=True)
        try:
            row = conn.execute("SELECT url FROM opportunity_source WHERE url IS NOT NULL AND url<>'' ORDER BY id LIMIT 1").fetchone()
            self.assertIsNotNone(row)
            result = resolve(row["url"], conn=conn)
            self.assertEqual(result["scheme"], "url")
            self.assertEqual(result["object_type"], "source")
            self.assertTrue(result["found"])
            self.assertIn("human_explanation", result)
        finally:
            conn.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
