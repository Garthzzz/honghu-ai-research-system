from __future__ import annotations

from tools.opportunity_lens.ab_readonly import ab_row_counts

from helpers import FixtureDBTestCase, make_test_app


class NoWriteGuaranteeTests(FixtureDBTestCase):
    def test_get_api_does_not_write_c_or_ab_databases(self):
        app = make_test_app(self.db_path, self.export_root)
        client = app.test_client()
        c_before = self.counts()
        ab_before = ab_row_counts()
        for path in [
            "/api/opportunity-lens/health",
            "/api/opportunity-lens/runs",
            "/api/opportunity-lens/run/1",
            "/api/opportunity-lens/run/1/intake",
            "/api/opportunity-lens/run/1/early-signals",
            "/api/opportunity-lens/run/1/entities",
            "/api/opportunity-lens/entity/1/score",
            "/api/opportunity-lens/run/1/visuals",
            "/api/opportunity-lens/evidence/resolve?ref=opp://source/1",
            "/api/opportunity-lens/export/1/status",
        ]:
            self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(c_before, self.counts())
        self.assertEqual(ab_before, ab_row_counts())


if __name__ == "__main__":
    import unittest

    unittest.main()
