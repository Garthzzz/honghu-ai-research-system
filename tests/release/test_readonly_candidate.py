from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.release.dev_fixture import build_dev_fixture


ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReadOnlyCandidateTests(unittest.TestCase):
    def test_synthetic_fixture_and_candidate_http_gate_do_not_write_databases(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / "fixture"
            payload = build_dev_fixture(fixture)
            self.assertTrue(payload["synthetic_only"])
            data = fixture / "data"
            before = {path.name: _sha256(path) for path in data.glob("*.db")}
            script = r"""
import json
from tools.viewer.app import app
client = app.test_client()
health = client.get('/api/health')
tools = client.get('/tools')
blocked = client.post('/api/analyst_note', json={})
print(json.dumps({
    'health': health.status_code,
    'health_mode': health.get_json().get('viewer_mode'),
    'tools': tools.status_code,
    'blocked': blocked.status_code,
}))
"""
            env = os.environ.copy()
            env.update(
                {
                    "HONGHU_DATA_ROOT": str(data),
                    "HONGHU_CONTENT_ROOT": str(fixture / "content"),
                    "HONGHU_STATE_ROOT": str(fixture / "state"),
                    "HONGHU_VIEWER_MODE": "readonly_candidate",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=env,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            outcome = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(outcome["health"], 200)
            self.assertEqual(outcome["health_mode"], "readonly_candidate")
            self.assertEqual(outcome["tools"], 200)
            self.assertEqual(outcome["blocked"], 403)
            after = {path.name: _sha256(path) for path in data.glob("*.db")}
            self.assertEqual(before, after)

    def test_vm_candidate_script_keeps_production_port_and_tasks_untouched(self):
        script = (ROOT / "tools/release/Deploy-ReadonlyCandidate.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("18080", script)
        self.assertIn("production_port_untouched = 8080", script)
        self.assertIn("scheduled_tasks_modified = $false", script)
        self.assertNotIn("Disable-ScheduledTask", script)
        self.assertNotIn("Enable-ScheduledTask", script)
        self.assertNotIn("Stop-ScheduledTask", script)


if __name__ == "__main__":
    unittest.main()
