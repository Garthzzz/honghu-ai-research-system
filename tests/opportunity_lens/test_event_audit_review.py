from __future__ import annotations

from tools.opportunity_lens.audit import issue_counts, waive_issue
from tools.opportunity_lens.db import connect
from tools.opportunity_lens.event_ledger import append_business_event
from tools.opportunity_lens.flags import run_flag_summary
from tools.opportunity_lens.review_workflow import apply_review_decision, enqueue_review

from helpers import FixtureDBTestCase


class EventAuditReviewTests(FixtureDBTestCase):
    def test_event_dedup_returns_existing_event(self):
        conn = connect(self.db_path)
        try:
            a = append_business_event(conn, 1, "A", "capacity_change", "fundamental", "positive", dedupe_key="same")
            b = append_business_event(conn, 1, "B", "capacity_change", "fundamental", "positive", dedupe_key="same")
            self.assertEqual(a, b)
        finally:
            conn.rollback()
            conn.close()

    def test_audit_flags_and_waiver(self):
        conn = connect(self.db_path)
        try:
            self.assertEqual(issue_counts(conn, 1)["open_p1"], 1)
            self.assertEqual(run_flag_summary(conn, 1)["level"], "yellow")
            with self.assertRaises(ValueError):
                waive_issue(conn, 1, "", "")
            waive_issue(conn, 1, "tester", "fixture waiver")
            self.assertEqual(issue_counts(conn, 1)["open_p1"], 0)
        finally:
            conn.rollback()
            conn.close()

    def test_review_decision_records_status(self):
        conn = connect(self.db_path)
        try:
            rid = enqueue_review(conn, 1, "opp://entity/1", entity_id=1)
            apply_review_decision(conn, rid, "approve", "tester", "ok")
            row = conn.execute("SELECT review_status FROM opportunity_review_queue WHERE id=?", (rid,)).fetchone()
            self.assertEqual(row["review_status"], "approved")
        finally:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
