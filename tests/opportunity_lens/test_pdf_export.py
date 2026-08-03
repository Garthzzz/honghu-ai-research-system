from __future__ import annotations

from pathlib import Path

from tools.opportunity_lens.db import connect

from helpers import FixtureDBTestCase, make_test_app


class PdfExportTests(FixtureDBTestCase):
    def setUp(self):
        super().setUp()
        self.app = make_test_app(self.db_path, self.export_root)
        self.client = self.app.test_client()

    def test_export_status_get_does_not_create_job(self):
        before = self.counts()
        res = self.client.get("/api/opportunity-lens/export/1/status")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["data"]["empty_state"], "export_not_requested")
        after = self.counts()
        self.assertEqual(before, after)

    def test_explicit_export_post_records_deferred_failure_manifest(self):
        res = self.client.post("/api/opportunity-lens/run/1/export-pdf")
        self.assertEqual(res.status_code, 202)
        data = res.get_json()["data"]
        self.assertEqual(data["job"]["export_status"], "failed")
        manifest = data["job"]["manifest"]
        self.assertIsNone(manifest["pdf_path"])
        self.assertIn("intake_contract_version", manifest)
        self.assertIn("evidence_policy_version", manifest)
        self.assertIn("early_signal_rule_version", manifest)
        self.assertEqual(manifest["intake_summary"]["research_question"], "合成 HBM 载板供需失衡扫描")
        self.assertEqual(manifest["early_signal_summary"]["count"], 1)
        self.assertFalse(manifest["early_signal_summary"]["core_score_changed_by_overlay"])
        self.assertIn("PDF 渲染器暂缓接入", manifest["error_message"])
        self.assertTrue(Path(manifest["html_snapshot_path"]).exists())
        page = self.client.get("/opportunity-lens/run/1/export")
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(page.headers.get("Location"))
        html = page.get_data(as_text=True)
        self.assertIn("导出状态", html)
        self.assertIn("真实 PDF renderer 尚未接入", html)
        conn = connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM opportunity_export_job").fetchone()[0], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
