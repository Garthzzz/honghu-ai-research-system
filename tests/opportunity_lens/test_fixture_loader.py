from __future__ import annotations

from helpers import FixtureDBTestCase
from tools.opportunity_lens.db import connect


class FixtureLoaderTests(FixtureDBTestCase):
    def test_fixture_loads_deterministic_run(self):
        conn = connect(self.db_path)
        try:
            run = conn.execute("SELECT * FROM opportunity_run WHERE id=1").fetchone()
            self.assertEqual(run["requested_by"], "synthetic_fixture")
            self.assertEqual(run["run_status"], "completed")
            self.assertEqual(run["run_readiness_status"], "reviewable")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_source").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_entity_maturation").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_intake_contract").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_early_signal_aggregate").fetchone()[0], 1)
        finally:
            conn.close()

    def test_fixture_event_dedupe(self):
        conn = connect(self.db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM opportunity_event_ledger WHERE dedupe_key='synthetic-hbm-substrate-capacity-2026q2'"
            ).fetchone()[0]
            self.assertEqual(n, 1)
        finally:
            conn.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
