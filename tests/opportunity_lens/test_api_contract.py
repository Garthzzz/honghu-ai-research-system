from __future__ import annotations

import json

from helpers import FixtureDBTestCase, make_test_app


def _contains_key(obj, forbidden: str) -> bool:
    if isinstance(obj, dict):
        return forbidden in obj or any(_contains_key(value, forbidden) for value in obj.values())
    if isinstance(obj, list):
        return any(_contains_key(value, forbidden) for value in obj)
    return False


class ApiContractTests(FixtureDBTestCase):
    def setUp(self):
        super().setUp()
        self.app = make_test_app(self.db_path, self.export_root)
        self.client = self.app.test_client()

    def test_envelope_and_health(self):
        res = self.client.get("/api/opportunity-lens/health")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        for key in ["ok", "contract_version", "module", "generated_at", "data"]:
            self.assertIn(key, body)
        self.assertTrue(body["data"]["db_exists"])

    def test_ranking_uses_entity_id_not_candidate_id(self):
        body = self.client.get("/api/opportunity-lens/run/1/entities").get_json()
        row = body["data"][0]
        self.assertIn("entity_id", row)
        self.assertNotIn("candidate_id", row)
        self.assertIn("maturation_status", row)
        self.assertIn("early_signal_score", row)

    def test_run_api_uses_research_question_not_legacy_question(self):
        body = self.client.get("/api/opportunity-lens/run/1").get_json()
        self.assertIn("research_question", body["data"])
        self.assertNotIn("question", body["data"])
        self.assertFalse(_contains_key(body["data"], "available_materials_state"))

    def test_intake_and_early_signal_endpoints(self):
        intake = self.client.get("/api/opportunity-lens/run/1/intake").get_json()["data"]
        self.assertEqual(intake["research_question"], "合成 HBM 载板供需失衡扫描")
        self.assertEqual(intake["available_materials_choice"], "A")
        self.assertEqual(intake["intake_material_type"], "none")
        signals = self.client.get("/api/opportunity-lens/run/1/early-signals").get_json()["data"]
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["core_score_changed_by_overlay"], 0)

    def test_score_contract_fields(self):
        body = self.client.get("/api/opportunity-lens/entity/1/score").get_json()
        data = body["data"]
        for key in ["entity_id", "score_status", "score_grade", "rating_status", "score_quality_label", "factor_scores"]:
            self.assertIn(key, data)
        self.assertIn("early_signal", data)
        self.assertEqual(data["early_signal"]["core_score_changed_by_overlay"], 0)
        first_factor = data["factor_scores"][0]
        for key in ["factor_label", "factor_formula", "factor_description", "factor_human_question"]:
            self.assertIn(key, first_factor)
            self.assertTrue(first_factor[key])

    def test_trace_contract_is_human_readable_before_json(self):
        entities = self.client.get("/api/opportunity-lens/entity/1/score").get_json()["data"]["factor_scores"]
        factor_id = entities[0]["id"]
        factor = self.client.get(f"/api/opportunity-lens/factor/{factor_id}/trace").get_json()["data"]
        for key in ["factor_label", "factor_formula", "factor_description", "human_explanation"]:
            self.assertIn(key, factor)
            self.assertTrue(factor[key])
        explanation = factor["human_explanation"]
        for key in ["headline", "formula", "plain_steps", "json_guide"]:
            self.assertIn(key, explanation)
            self.assertTrue(explanation[key])

    def test_visual_contract_uses_human_labels_before_codes(self):
        visuals = self.client.get("/api/opportunity-lens/run/1/visuals").get_json()["data"]
        heatmap = next(item for item in visuals if item["block_key"] == "factor_heatmap")
        columns = heatmap["display_data"]["columns"]
        self.assertEqual(columns[0], "因子中文名")
        self.assertIn("计算公式", columns)
        labels = [row[0] for row in heatmap["display_data"]["rows"]]
        self.assertIn("下游价格动量", labels)
        self.assertIn("factor_label", heatmap["data"]["factors"][0])
        factor_scores = [row["score_adjusted"] for row in heatmap["data"]["factors"]]
        self.assertEqual(factor_scores, sorted(factor_scores, reverse=True))
        display_score_index = columns.index("调整后分数")
        display_scores = [row[display_score_index] for row in heatmap["display_data"]["rows"]]
        self.assertEqual(display_scores, sorted(display_scores, reverse=True))

    def test_bad_evidence_uri_error(self):
        res = self.client.get("/api/opportunity-lens/evidence/resolve?ref=opp://unknown/1")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["ok"])

    def test_public_create_rejects_legacy_question_alias(self):
        res = self.client.post(
            "/api/opportunity-lens/run",
            data=json.dumps({"question": "legacy"}),
            content_type="application/json",
            headers={"X-Idempotency-Key": "k1", "X-Actor": "tester", "X-Reason": "contract test"},
        )
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    import unittest

    unittest.main()
