from __future__ import annotations

from tools.opportunity_lens.candidate_builder import create_candidate, promote_candidate_to_entity
from tools.opportunity_lens.db import connect
from tools.opportunity_lens.search_models import add_search_task, create_search_plan, log_search_decision
from tools.opportunity_lens.workflow import advance_run, create_run

from helpers import FixtureDBTestCase


class ResearchWorkflowTests(FixtureDBTestCase):
    def test_candidate_promotion_uses_canonical_entity(self):
        conn = connect(self.db_path)
        try:
            run_id = create_run(conn, "workflow test")
            cand_id = create_candidate(conn, run_id, "Workflow Material", "product")
            entity_id = promote_candidate_to_entity(conn, cand_id)
            cand = conn.execute("SELECT * FROM opportunity_candidate_entity WHERE id=?", (cand_id,)).fetchone()
            entity = conn.execute("SELECT * FROM opportunity_entity WHERE id=?", (entity_id,)).fetchone()
            self.assertEqual(cand["candidate_stage"], "merged_to_entity")
            self.assertEqual(entity["entity_type"], "product_material")
        finally:
            conn.rollback()
            conn.close()

    def test_search_plan_records_decisions(self):
        conn = connect(self.db_path)
        try:
            run_id = create_run(conn, "search test")
            advance_run(conn, run_id, "intake_validated", "test")
            plan_id = create_search_plan(conn, run_id, "plan", [{"axis_key": "supply"}], ["official"])
            task_id = add_search_task(conn, run_id, plan_id, "supply", "official", "query", "completed")
            log_id = log_search_decision(conn, run_id, "included", "source", task_id)
            self.assertGreater(log_id, 0)
        finally:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
