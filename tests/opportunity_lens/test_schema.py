from __future__ import annotations

import sqlite3

from tools.opportunity_lens.constants import SCHEMA_VERSION
from tools.opportunity_lens.migrate import REQUIRED_TABLES, verify_schema

from helpers import FixtureDBTestCase


class SchemaTests(FixtureDBTestCase):
    def test_schema_tables_and_meta(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            verify_schema(conn)
            tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue(REQUIRED_TABLES.issubset(tables))
            self.assertEqual(conn.execute("SELECT value FROM opportunity_schema_meta WHERE key='schema_version'").fetchone()["value"], SCHEMA_VERSION)
            run_cols = {r[1] for r in conn.execute("PRAGMA table_info(opportunity_run)").fetchall()}
            self.assertIn("research_question", run_cols)
            self.assertIn("evidence_policy", run_cols)
            manifest_cols = {r[1] for r in conn.execute("PRAGMA table_info(opportunity_run_manifest)").fetchall()}
            self.assertIn("intake_contract_version", manifest_cols)
            self.assertIn("evidence_policy_version", manifest_cols)
            self.assertIn("early_signal_rule_version", manifest_cols)
            slot_cols = {r[1] for r in conn.execute("PRAGMA table_info(opportunity_metric_slot)").fetchall()}
            self.assertIn("policy_gate_verdict", slot_cols)
            self.assertIn("scoring_eligibility", slot_cols)
            target_cols = {r[1] for r in conn.execute("PRAGMA table_info(opportunity_entity_investment_target)").fetchall()}
            self.assertIn("target_name", target_cols)
            self.assertIn("target_type", target_cols)
            self.assertIn("investment_view", target_cols)
            self.assertIn("risk_note", target_cols)
            self.assertIn("target_priority", target_cols)
            self.assertIn("target_quality_label", target_cols)
            self.assertIn("relative_preference", target_cols)
            self.assertIn("confirmed_scenario_action", target_cols)
            self.assertIn("falsified_scenario_action", target_cols)
            self.assertIn("target_profile_markdown", target_cols)
            self.assertIn("target_deep_research_markdown", target_cols)
            self.assertIn("entity_relation_markdown", target_cols)
            self.assertIn("parent_research_relation_markdown", target_cols)
            self.assertIn("conditional_investment_recommendation", target_cols)
            self.assertIn("financial_data_status", target_cols)
            self.assertIn("link_status", target_cols)
            target_dp_cols = {r[1] for r in conn.execute("PRAGMA table_info(opportunity_target_data_point)").fetchall()}
            self.assertIn("target_id", target_dp_cols)
            self.assertIn("metric_name", target_dp_cols)
            self.assertIn("source_excerpt", target_dp_cols)
            self.assertIn("weighted_contribution", target_dp_cols)
            source_cols = {r[1] for r in conn.execute("PRAGMA table_info(opportunity_source)").fetchall()}
            self.assertIn("event_date", source_cols)
            self.assertIn("fetch_date", source_cols)
            self.assertIn("local_locator", source_cols)
        finally:
            conn.close()

    def test_entity_has_no_global_maturation_status(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(opportunity_entity)").fetchall()}
            self.assertNotIn("maturation_status", cols)
            mat_cols = {r[1] for r in conn.execute("PRAGMA table_info(opportunity_entity_maturation)").fetchall()}
            self.assertIn("maturation_status", mat_cols)
        finally:
            conn.close()

    def test_check_constraints_reject_bad_status(self):
        conn = sqlite3.connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO opportunity_run(
                      question, run_mode, run_status, run_readiness_status,
                      schema_version, api_contract_version, score_rule_version,
                      source_tier_version, search_protocol_version, report_template_version,
                      pdf_export_version
                    ) VALUES('bad','c_open','score_ready','draft','s','a','r','t','p','rt','pdf')
                    """
                )
        finally:
            conn.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
