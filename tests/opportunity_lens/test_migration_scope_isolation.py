from __future__ import annotations

from tools.opportunity_lens.db import connect
from tools.opportunity_lens.migrate import init_db

from helpers import FixtureDBTestCase


class MigrationScopeIsolationTest(FixtureDBTestCase):
    def test_reopening_current_schema_does_not_backfill_historic_manifest_rows(self):
        conn = connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO opportunity_run_manifest(
                  run_id, manifest_type, manifest_json, manifest_hash,
                  intake_contract_version, evidence_policy_version,
                  early_signal_rule_version, workflow_contract_version,
                  pack_schema_version
                ) VALUES(?,?,?,?,NULL,NULL,NULL,?,?)
                """,
                (
                    self.run_id,
                    "browser_visual_audit",
                    '{"historic":true}',
                    "historic-browser-audit",
                    "research.workflow.v2",
                    "opportunity_lens.run_pack.v2",
                ),
            )
            manifest_id = int(cursor.lastrowid)
            conn.commit()
            before = tuple(
                conn.execute(
                    "SELECT * FROM opportunity_run_manifest WHERE id=?",
                    (manifest_id,),
                ).fetchone()
            )
        finally:
            conn.close()

        init_db(self.db_path, reset=False)

        conn = connect(self.db_path)
        try:
            after = tuple(
                conn.execute(
                    "SELECT * FROM opportunity_run_manifest WHERE id=?",
                    (manifest_id,),
                ).fetchone()
            )
        finally:
            conn.close()
        self.assertEqual(before, after)

