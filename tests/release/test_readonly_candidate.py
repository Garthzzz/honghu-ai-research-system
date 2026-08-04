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
from tools.release.readonly_smoke import build_representative_plan
from tools.runtime_paths import resolve_content_reference


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
home = client.get('/')
industry = client.get('/industry/1')
valuation = client.get('/industry/1/valuation')
company = client.get('/company/1')
sentiment = client.get('/dynamic/sentiment')
opportunity = client.get('/opportunity-lens')
opportunity_run = client.get('/opportunity-lens/run/1')
tools = client.get('/tools')
pdf = client.get('/pdf/1')
blocked = client.post('/api/analyst_note', json={})
print(json.dumps({
    'health': health.status_code,
    'health_mode': health.get_json().get('viewer_mode'),
    'home': home.status_code,
    'industry': industry.status_code,
    'valuation': valuation.status_code,
    'company': company.status_code,
    'sentiment': sentiment.status_code,
    'opportunity': opportunity.status_code,
    'opportunity_run': opportunity_run.status_code,
    'tools': tools.status_code,
    'pdf': pdf.status_code,
    'pdf_type': pdf.content_type,
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
            for key in (
                "home", "industry", "valuation", "company", "sentiment",
                "opportunity", "opportunity_run",
            ):
                self.assertEqual(outcome[key], 200, (key, outcome))
            self.assertEqual(outcome["tools"], 200)
            self.assertEqual(outcome["pdf"], 200)
            self.assertTrue(outcome["pdf_type"].startswith("application/pdf"))
            self.assertEqual(outcome["blocked"], 403)
            after = {path.name: _sha256(path) for path in data.glob("*.db")}
            self.assertEqual(before, after)

    def test_vm_candidate_script_collects_real_evidence_and_has_safe_lifecycle(self):
        script = (ROOT / "tools/release/Deploy-ReadonlyCandidate.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("18080", script)
        self.assertIn("BootstrapPythonExe", script)
        self.assertIn("Get-HonghuScheduledTaskSnapshot", script)
        self.assertIn("Get-HonghuProductionState", script)
        self.assertIn("Stop-HonghuVerifiedCandidate", script)
        self.assertIn("tools.release.readonly_smoke", script)
        self.assertIn('"-B", "-m", "tools.release.cli"', script)
        self.assertIn("--preflight-report-sha256", script)
        self.assertNotIn("production_port_untouched = 8080", script)
        self.assertNotIn("scheduled_tasks_modified = $false", script)
        self.assertNotIn("Disable-ScheduledTask", script)
        self.assertNotIn("Enable-ScheduledTask", script)
        self.assertNotIn("Stop-ScheduledTask", script)

        cli = (ROOT / "tools/release/cli.py").read_text(encoding="utf-8")
        self.assertIn("use_reloader=False", cli)
        self.assertNotIn("subprocess.call", cli)

    def test_runtime_content_resolution_and_representative_plan_use_external_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / "fixture"
            build_dev_fixture(fixture)
            content = fixture / "content"
            pdf = resolve_content_reference(content, "papers/fixture.pdf", default_prefix="papers")
            # GitHub's Windows runner may expose the temporary root through an
            # 8.3 alias while Path.resolve() returns the canonical long name.
            # Compare the existing file identity, not two textual spellings of
            # the same Windows path.
            self.assertTrue(pdf.samefile(content / "papers" / "fixture.pdf"))
            with self.assertRaises(ValueError):
                resolve_content_reference(content, "../outside.pdf", default_prefix="papers")
            plan = build_representative_plan(fixture / "data", content)
            categories = {item.category for item in plan}
            self.assertIn("external-paper", categories)
            self.assertIn("research-financial-and-sentiment", categories)
            self.assertIn("opportunity-run-detail", categories)
            self.assertIn("tracked-model", categories)

    def test_powershell_contract_parses_and_refuses_mismatched_pid_identity(self):
        scripts = [
            ROOT / "tools/release/CandidateProcess.ps1",
            ROOT / "tools/release/Deploy-ReadonlyCandidate.ps1",
            ROOT / "tools/release/Stop-ReadonlyCandidate.ps1",
        ]
        for script in scripts:
            command = (
                "$t=$null;$e=$null;"
                f"[System.Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$t,[ref]$e)|Out-Null;"
                "if($e.Count){$e|ForEach-Object{$_.Message};exit 1}"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "candidate.json"
            record.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "start_time_utc": "2000-01-01T00:00:00.0000000Z",
                        "executable_path": sys.executable,
                        "command_line_sha256": "0" * 64,
                        "launch_id": "0" * 32,
                        "commit_sha": "0" * 40,
                        "port": 18080,
                    }
                ),
                encoding="utf-8",
            )
            helper = ROOT / "tools/release/CandidateProcess.ps1"
            command = (
                f". '{helper}';"
                f"Stop-HonghuVerifiedCandidate -RecordPath '{record}' | Out-Null"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(record.is_file())


if __name__ == "__main__":
    unittest.main()
