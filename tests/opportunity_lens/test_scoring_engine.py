from __future__ import annotations

import json

from tools.opportunity_lens.db import connect
from tools.opportunity_lens.scoring import create_score_batch
from tools.opportunity_lens.score_trace import get_entity_score_trace
from tools.opportunity_lens.state_registry import ENUMS

from helpers import FixtureDBTestCase


class ScoringEngineTests(FixtureDBTestCase):
    def test_current_score_trace_uses_entity_id(self):
        conn = connect(self.db_path)
        try:
            trace = get_entity_score_trace(conn, 1)
            self.assertEqual(trace["entity_id"], 1)
            self.assertNotIn("candidate_id", trace)
            self.assertEqual(trace["score_status"], "complete")
            self.assertIn(trace["score_grade"], ENUMS["score_grade"])
            self.assertTrue(trace["evidence_ref_uri_list"])
        finally:
            conn.close()

    def test_append_only_score_batch(self):
        conn = connect(self.db_path)
        try:
            first = conn.execute("SELECT id FROM opportunity_score_batch WHERE is_current=1").fetchone()["id"]
            second = create_score_batch(conn, 1, entity_ids=[1])
            conn.commit()
            self.assertNotEqual(first, second)
            self.assertEqual(conn.execute("SELECT score_batch_status FROM opportunity_score_batch WHERE id=?", (first,)).fetchone()[0], "superseded")
            self.assertEqual(conn.execute("SELECT is_current FROM opportunity_score_batch WHERE id=?", (second,)).fetchone()[0], 1)
        finally:
            conn.close()

    def test_veto_rows_identify_codes(self):
        conn = connect(self.db_path)
        try:
            batch = conn.execute("SELECT id FROM opportunity_score_batch WHERE is_current=1").fetchone()["id"]
            codes = [r["veto_code"] for r in conn.execute("SELECT veto_code FROM opportunity_veto_status WHERE score_batch_id=? AND entity_id=1", (batch,))]
            self.assertEqual(set(codes), set(ENUMS["veto_code"]))
        finally:
            conn.close()

    def test_early_signal_slot_is_excluded_from_core_score(self):
        conn = connect(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT fs.factor_trace_json
                FROM opportunity_factor_score fs
                WHERE fs.run_id=1 AND fs.entity_id=1 AND fs.factor_code='demand.downstream_price_momentum'
                ORDER BY fs.id DESC LIMIT 1
                """
            ).fetchone()
            trace = json.loads(row["factor_trace_json"])
            excluded = trace["excluded_non_core_inputs"]
            included = trace["included_core_inputs"]
            self.assertIn("opp://metric_slot/11", excluded)
            self.assertNotIn("opp://metric_slot/11", included)
            self.assertEqual(trace["coverage"], 1.0)
        finally:
            conn.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
