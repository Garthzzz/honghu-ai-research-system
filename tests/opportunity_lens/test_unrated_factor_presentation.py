from __future__ import annotations

import json

from tools.opportunity_lens.db import connect

from helpers import FixtureDBTestCase, make_test_app


class UnratedFactorPresentationTest(FixtureDBTestCase):
    def setUp(self):
        super().setUp()
        conn = connect(self.db_path)
        try:
            factor = conn.execute(
                """
                SELECT id, entity_id, factor_code
                FROM opportunity_factor_score
                WHERE run_id=?
                ORDER BY id LIMIT 1
                """,
                (self.run_id,),
            ).fetchone()
            self.factor_id = int(factor["id"])
            self.entity_id = int(factor["entity_id"])
            conn.execute(
                """
                UPDATE opportunity_factor_score
                SET score_status='insufficient_evidence', score_raw=50, score_adjusted=50,
                    coverage=0.2, reliability_multiplier=0
                WHERE id=?
                """,
                (self.factor_id,),
            )
            conn.execute(
                """
                UPDATE opportunity_factor_readiness
                SET factor_readiness_status='missing',
                    missing_reason='缺少可直接复算的下游产品三个月价格变化。'
                WHERE run_id=? AND factor_code=?
                """,
                (self.run_id, factor["factor_code"]),
            )
            rows = conn.execute(
                """
                SELECT id, data_json
                FROM opportunity_visual_block
                WHERE run_id=? AND block_type='heatmap'
                """,
                (self.run_id,),
            ).fetchall()
            for row in rows:
                payload = json.loads(row["data_json"] or "{}")
                changed = False
                for item in payload.get("factors") or []:
                    if int(item.get("id") or 0) == self.factor_id:
                        item["score_status"] = "insufficient_evidence"
                        item["factor_readiness_status"] = "missing"
                        item["score_adjusted"] = 50
                        changed = True
                if changed:
                    conn.execute(
                        "UPDATE opportunity_visual_block SET data_json=? WHERE id=?",
                        (json.dumps(payload, ensure_ascii=False), row["id"]),
                    )
            conn.commit()
        finally:
            conn.close()
        self.app = make_test_app(self.db_path, self.export_root)
        self.client = self.app.test_client()

    def test_heatmap_and_factor_page_do_not_present_neutral_placeholder_as_score(self):
        run_html = self.client.get(f"/opportunity-lens/run/{self.run_id}").get_data(as_text=True)
        self.assertIn("heat-unrated", run_html)
        self.assertIn("证据不足", run_html)
        self.assertIn("点击查看缺少哪些指标", run_html)
        self.assertIn("缺少可直接复算的下游产品三个月价格变化", run_html)

        factor_html = self.client.get(
            f"/opportunity-lens/factor/{self.factor_id}"
        ).get_data(as_text=True)
        self.assertIn("证据不足，暂不评分", factor_html)
        self.assertIn("目前证据覆盖不足，暂不形成正式评分", factor_html)
        self.assertIn("证据不足时不展示分数", factor_html)
        self.assertIn("如果想提高本因子的证据覆盖，需要补充", factor_html)
        self.assertIn("下游产品三个月价格变化", factor_html)
        self.assertNotIn("向中性收敛的内部计算值", factor_html)
        self.assertNotIn("调整后分数</span><b>50.0", factor_html)

        entity_html = self.client.get(
            f"/opportunity-lens/entity/{self.entity_id}"
        ).get_data(as_text=True)
        self.assertIn("缺少可直接复算的下游产品三个月价格变化", entity_html)
        entity_payload = self.client.get(
            f"/api/opportunity-lens/entity/{self.entity_id}"
        ).get_json()["data"]
        matching = [
            item for item in entity_payload["score"]["factor_scores"]
            if int(item["id"]) == self.factor_id
        ]
        self.assertEqual(
            matching[0]["missing_reason"],
            "缺少可直接复算的下游产品三个月价格变化。",
        )

        conn = connect(self.db_path)
        try:
            slot_id = int(
                conn.execute(
                    """
                    SELECT id FROM opportunity_metric_slot
                    WHERE run_id=? AND value_status NOT IN ('available','calculated','stale_but_usable')
                    ORDER BY id LIMIT 1
                    """,
                    (self.run_id,),
                ).fetchone()[0]
            )
        finally:
            conn.close()
        slot_html = self.client.get(
            f"/opportunity-lens/metric-slot/{slot_id}"
        ).get_data(as_text=True)
        self.assertIn("<span>分数</span><b>证据不足</b>", slot_html)
        self.assertNotIn("<span>分数</span><b>None</b>", slot_html)

    def test_complete_score_is_hidden_when_readiness_is_blocked(self):
        conn = connect(self.db_path)
        try:
            factor = conn.execute(
                "SELECT factor_code FROM opportunity_factor_score WHERE id=?",
                (self.factor_id,),
            ).fetchone()
            conn.execute(
                """
                UPDATE opportunity_factor_score
                SET score_status='complete', score_raw=73, score_adjusted=71
                WHERE id=?
                """,
                (self.factor_id,),
            )
            conn.execute(
                """
                UPDATE opportunity_factor_readiness
                SET factor_readiness_status='conflict_blocked'
                WHERE run_id=? AND factor_code=?
                """,
                (self.run_id, factor["factor_code"]),
            )
            conn.commit()
        finally:
            conn.close()

        factor_html = self.client.get(
            f"/opportunity-lens/factor/{self.factor_id}"
        ).get_data(as_text=True)
        self.assertIn("目前证据覆盖不足，暂不形成正式评分", factor_html)
        self.assertNotIn("调整后分数</span><b>71.0", factor_html)
        entity_html = self.client.get(
            f"/opportunity-lens/entity/{self.entity_id}"
        ).get_data(as_text=True)
        self.assertNotIn(">71.0</td>", entity_html)
