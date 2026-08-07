from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path

from tools.release.dev_fixture import build_dev_fixture
from tools.release.readonly_smoke import build_representative_plan
from tools.runtime_paths import resolve_content_reference


ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


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
theme = client.get('/theme/fixture-theme')
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
    'theme': theme.status_code,
    'theme_has_db_summary': '数据库承载的主题摘要' in theme.get_data(as_text=True),
    'theme_reports_missing_optional_md': '尚无主题分析 md' in theme.get_data(as_text=True),
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
                "home", "industry", "valuation", "company", "theme", "sentiment",
                "opportunity", "opportunity_run",
            ):
                self.assertEqual(outcome[key], 200, (key, outcome))
            self.assertEqual(outcome["tools"], 200)
            self.assertTrue(outcome["theme_has_db_summary"])
            self.assertTrue(outcome["theme_reports_missing_optional_md"])
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
        self.assertIn("runtimeVerificationText", script)
        self.assertIn("$evidence.observed.python_runtime = $runtimeVerification", script)
        self.assertIn("Candidate Python runtime verification did not return valid JSON", script)
        self.assertIn("$listenerPython = [string]$runtimeVerification.base_python_executable", script)
        self.assertIn("$lockedSitePackages = [string]$runtimeVerification.site_packages", script)
        self.assertIn('"-I", "-B", "-S", $listenerBootstrap', script)
        self.assertIn("Start-Process -FilePath $listenerPython", script)
        self.assertNotIn("Start-Process -FilePath $venvPython", script)
        self.assertNotIn("$venvPython -m tools.release", script)
        self.assertIn("--quarantine-invalid-inactive", script)
        self.assertIn("Get-HonghuExactReleaseVerification", script)
        self.assertIn("after_smoke", script)
        self.assertIn("evidence_history", script)
        self.assertIn("--preflight-report-sha256", script)
        self.assertNotIn("production_port_untouched = 8080", script)
        self.assertNotIn("scheduled_tasks_modified = $false", script)
        self.assertNotIn("Disable-ScheduledTask", script)
        self.assertNotIn("Enable-ScheduledTask", script)
        self.assertNotIn("Stop-ScheduledTask", script)

        cli = (ROOT / "tools/release/cli.py").read_text(encoding="utf-8")
        self.assertIn("use_reloader=False", cli)
        self.assertNotIn("subprocess.call", cli)

    def test_isolated_bootstrap_ignores_pythonpath_and_never_writes_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release = root / "release"
            malicious = root / "malicious"
            for package_root in (release, malicious):
                (package_root / "tools/release").mkdir(parents=True)
                (package_root / "tools/__init__.py").write_text("", encoding="utf-8")
                (package_root / "tools/release/__init__.py").write_text("", encoding="utf-8")
            (release / "tools/release/direct_candidate.py").write_text(
                (ROOT / "tools/release/direct_candidate.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            good_marker = root / "good.txt"
            bad_marker = root / "bad.txt"
            (release / "tools/release/cli.py").write_text(
                "from pathlib import Path\n"
                f"def main(argv=None): Path({str(good_marker)!r}).write_text('good'); return 0\n",
                encoding="utf-8",
            )
            (malicious / "tools/release/cli.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(bad_marker)!r}).write_text('bad')\n"
                "def main(argv=None): return 0\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.pop("PYTHONDONTWRITEBYTECODE", None)
            env["PYTHONPATH"] = str(malicious)
            command = [
                str(Path(getattr(sys, "_base_executable", sys.executable)).resolve()),
                "-I",
                "-B",
                "-S",
                str(release / "tools/release/direct_candidate.py"),
                "--site-packages",
                str(Path(sysconfig.get_path("purelib")).resolve()),
                "--module",
                "tools.release.cli",
                "verify",
            ]
            result = subprocess.run(
                command,
                cwd=malicious,
                env=env,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(good_marker.is_file())
            self.assertFalse(bad_marker.exists())
            self.assertFalse(any(release.rglob("*.pyc")))

    def test_direct_bootstrap_overrides_legacy_windows_output_encoding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release = root / "release"
            (release / "tools/release").mkdir(parents=True)
            (release / "tools/__init__.py").write_text("", encoding="utf-8")
            (release / "tools/release/__init__.py").write_text("", encoding="utf-8")
            (release / "tools/release/direct_candidate.py").write_text(
                (ROOT / "tools/release/direct_candidate.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (release / "tools/release/readonly_smoke.py").write_text(
                "def main(argv=None):\n"
                "    print('{\"summary\": \"数据库承载的主题摘要\"}')\n"
                "    return 0\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "cp1252"
            result = subprocess.run(
                [
                    str(Path(getattr(sys, "_base_executable", sys.executable)).resolve()),
                    "-B",
                    "-S",
                    str(release / "tools/release/direct_candidate.py"),
                    "--site-packages",
                    str(Path(sysconfig.get_path("purelib")).resolve()),
                    "--module",
                    "tools.release.readonly_smoke",
                    "--emit",
                ],
                cwd=release,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                result.stderr.decode("utf-8", errors="replace"),
            )
            self.assertIn("数据库承载的主题摘要", result.stdout.decode("utf-8"))
            self.assertFalse(any(release.rglob("*.pyc")))

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
            self.assertIn("research-theme-with-optional-markdown", categories)
            theme_check = next(item for item in plan if item.check_id == "theme-db-only")
            self.assertEqual(theme_check.path, "/theme/fixture-theme")
            self.assertEqual(theme_check.expected_body_contains, "尚无主题分析 md")

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

    def test_legacy_production_health_without_viewer_mode_is_reachable_and_stable(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        with tempfile.TemporaryDirectory() as temp:
            script = rf"""
. '{helper}'
function Invoke-WebRequest {{
    param([switch]$UseBasicParsing, $Uri, $TimeoutSec)
    [pscustomobject]@{{ StatusCode = 200; Content = '{{"release_version":"legacy-1","app_sha256":"abc"}}' }}
}}
function Get-NetTCPConnection {{
    param($State, $LocalPort, $ErrorAction)
    [pscustomobject]@{{ OwningProcess = 4321; LocalPort = 8080 }}
}}
$before = Get-HonghuProductionState -Root '{temp}'
$after = Get-HonghuProductionState -Root '{temp}'
[ordered]@{{ state = $before; comparison = (Test-HonghuProductionUnchanged $before $after) }} | ConvertTo-Json -Depth 12 -Compress
"""
            result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        health = payload["state"]["health"]
        self.assertTrue(health["reachable"])
        self.assertTrue(health["payload_parsed"])
        self.assertNotIn("viewer_mode", health["present_identity_fields"])
        self.assertIn("viewer_mode", health["missing_identity_fields"])
        self.assertTrue(payload["comparison"]["verified"], payload)
        self.assertFalse(
            payload["comparison"]["identity_fields"]["viewer_mode"]["before_present"]
        )

    def test_production_health_true_outage_and_identity_change_fail_closed(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        with tempfile.TemporaryDirectory() as temp:
            changed = rf"""
. '{helper}'
$global:healthCall = 0
function Invoke-WebRequest {{
    param([switch]$UseBasicParsing, $Uri, $TimeoutSec)
    $global:healthCall += 1
    $version = if ($global:healthCall -eq 1) {{ 'one' }} else {{ 'two' }}
    [pscustomobject]@{{ StatusCode = 200; Content = ('{{"release_version":"' + $version + '"}}') }}
}}
function Get-NetTCPConnection {{ param($State,$LocalPort,$ErrorAction); [pscustomobject]@{{OwningProcess=9;LocalPort=8080}} }}
$before=Get-HonghuProductionState -Root '{temp}';$after=Get-HonghuProductionState -Root '{temp}'
Test-HonghuProductionUnchanged $before $after | ConvertTo-Json -Depth 10 -Compress
"""
            changed_result = _run_powershell(changed)
            outage = rf"""
. '{helper}'
function Invoke-WebRequest {{ param([switch]$UseBasicParsing,$Uri,$TimeoutSec); throw 'connection refused' }}
function Get-NetTCPConnection {{ param($State,$LocalPort,$ErrorAction); [pscustomobject]@{{OwningProcess=9;LocalPort=8080}} }}
$before=Get-HonghuProductionState -Root '{temp}';$after=Get-HonghuProductionState -Root '{temp}'
Test-HonghuProductionUnchanged $before $after | ConvertTo-Json -Depth 10 -Compress
"""
            outage_result = _run_powershell(outage)
        self.assertEqual(changed_result.returncode, 0, changed_result.stderr)
        changed_payload = json.loads(changed_result.stdout.strip().splitlines()[-1])
        self.assertFalse(changed_payload["verified"])
        self.assertTrue(any("release_version" in x for x in changed_payload["reasons"]))
        self.assertEqual(outage_result.returncode, 0, outage_result.stderr)
        outage_payload = json.loads(outage_result.stdout.strip().splitlines()[-1])
        self.assertFalse(outage_payload["verified"])
        self.assertTrue(any("not reachable" in x for x in outage_payload["reasons"]))

    def test_production_state_window_tolerates_one_transient_sample_with_two_stable_samples(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        with tempfile.TemporaryDirectory() as temp:
            script = rf"""
. '{helper}'
$global:healthCall = 0
function Invoke-WebRequest {{
    param([switch]$UseBasicParsing, $Uri, $TimeoutSec, $ErrorAction)
    $global:healthCall += 1
    if ($global:healthCall -eq 1) {{ throw 'transient connection reset' }}
    [pscustomobject]@{{ StatusCode = 200; Content = '{{"release_version":"legacy-1","app_sha256":"abc"}}' }}
}}
function Get-NetTCPConnection {{
    param($State, $LocalPort, $ErrorAction)
    [pscustomobject]@{{ OwningProcess = 4321; LocalPort = 8080 }}
}}
Get-HonghuProductionStateWindow -Root '{temp}' -Attempts 3 -RequiredUsableSamples 2 -DelayMilliseconds 0 | ConvertTo-Json -Depth 20 -Compress
"""
            result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload["verified"], payload)
        self.assertEqual(payload["usable_sample_count"], 2)
        self.assertFalse(payload["samples"][0]["usable"])
        self.assertTrue(payload["samples"][1]["usable"])
        self.assertTrue(payload["samples"][2]["usable"])
        self.assertTrue(payload["warnings"])

    def test_production_state_window_records_pid_drift_without_rejecting_stable_authority(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        with tempfile.TemporaryDirectory() as temp:
            script = rf"""
. '{helper}'
$global:healthCall = 0
function Invoke-WebRequest {{
    param([switch]$UseBasicParsing, $Uri, $TimeoutSec, $ErrorAction)
    $global:healthCall += 1
    [pscustomobject]@{{ StatusCode = 200; Content = '{{"release_version":"legacy-1","release_manifest_sha256":"manifest","app_sha256":"app"}}' }}
}}
function Get-NetTCPConnection {{
    param($State, $LocalPort, $ErrorAction)
    $changingPid = if ($global:healthCall -eq 2) {{ 4604 }} else {{ 5000 }}
    @(
        [pscustomobject]@{{ OwningProcess = $changingPid; LocalPort = 8080 }},
        [pscustomobject]@{{ OwningProcess = 16332; LocalPort = 8080 }}
    )
}}
Get-HonghuProductionStateWindow -Root '{temp}' -Attempts 3 -RequiredUsableSamples 2 -DelayMilliseconds 0 | ConvertTo-Json -Depth 30 -Compress
"""
            result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload["verified"], payload)
        self.assertTrue(payload["hard_identity_quorum_verified"])
        self.assertEqual(payload["selected_quorum_attempts"], [1, 2, 3])
        self.assertTrue(
            payload["runtime_listener"]["pid_drift_within_selected_quorum"]
        )
        self.assertTrue(any("PID drift" in item for item in payload["warnings"]))

    def test_production_state_window_selects_two_of_three_authority_quorum(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        with tempfile.TemporaryDirectory() as temp:
            script = rf"""
. '{helper}'
$global:healthCall = 0
function Invoke-WebRequest {{
    param([switch]$UseBasicParsing, $Uri, $TimeoutSec, $ErrorAction)
    $global:healthCall += 1
    $version = if ($global:healthCall -eq 2) {{ 'transient-other' }} else {{ 'stable' }}
    [pscustomobject]@{{ StatusCode = 200; Content = ('{{"release_version":"' + $version + '","app_sha256":"app"}}') }}
}}
function Get-NetTCPConnection {{
    param($State, $LocalPort, $ErrorAction)
    [pscustomobject]@{{ OwningProcess = 4321; LocalPort = 8080 }}
}}
Get-HonghuProductionStateWindow -Root '{temp}' -Attempts 3 -RequiredUsableSamples 2 -DelayMilliseconds 0 | ConvertTo-Json -Depth 30 -Compress
"""
            result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload["verified"], payload)
        self.assertEqual(payload["selected_quorum_attempts"], [1, 3])
        self.assertEqual(payload["authority_outlier_attempts"], [2])
        self.assertEqual(len(payload["authority_clusters"]), 2)
        self.assertTrue(any("authority outlier" in item for item in payload["warnings"]))

    def test_production_state_window_rejects_real_identity_change(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        with tempfile.TemporaryDirectory() as temp:
            script = rf"""
. '{helper}'
$global:healthCall = 0
function Invoke-WebRequest {{
    param([switch]$UseBasicParsing, $Uri, $TimeoutSec, $ErrorAction)
    $global:healthCall += 1
    $version = @('one', 'two', 'three')[$global:healthCall - 1]
    [pscustomobject]@{{ StatusCode = 200; Content = ('{{"release_version":"' + $version + '"}}') }}
}}
function Get-NetTCPConnection {{
    param($State, $LocalPort, $ErrorAction)
    [pscustomobject]@{{ OwningProcess = 4321; LocalPort = 8080 }}
}}
Get-HonghuProductionStateWindow -Root '{temp}' -Attempts 3 -RequiredUsableSamples 2 -DelayMilliseconds 0 | ConvertTo-Json -Depth 20 -Compress
"""
            result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(payload["verified"], payload)
        self.assertEqual(payload["usable_sample_count"], 3)
        self.assertTrue(any("no production authority identity" in x for x in payload["reasons"]))

    def test_listener_disappearance_fails_but_pid_drift_uses_same_pre_post_semantics(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        with tempfile.TemporaryDirectory() as temp:
            script = rf"""
. '{helper}'
function New-TestState([int[]]$Pids) {{
    [ordered]@{{
        health = [ordered]@{{ reachable=$true; status=200; payload_parsed=$true; identity=[ordered]@{{release_version='stable';release_manifest_sha256='manifest';app_sha256='app'}} }}
        listener = [ordered]@{{ query_succeeded=$true; pids=@($Pids); error=$null }}
        listener_pids = @($Pids)
        current_pointer = [ordered]@{{ exists=$false; sha256=$null }}
        broadcast_manifest = [ordered]@{{ exists=$true; sha256='broadcast' }}
    }}
}}
$before = New-TestState @(5000,16332)
$sample1 = [ordered]@{{attempt=1;usable=$true;state=(New-TestState @(5000,16332))}}
$sample2 = [ordered]@{{attempt=2;usable=$true;state=(New-TestState @(4604,16332))}}
$sample3 = [ordered]@{{attempt=3;usable=$true;state=(New-TestState @(5000,16332))}}
$window = [ordered]@{{
    verified=$true; reasons=@(); warnings=@('listener PID drift occurred inside the selected authority quorum; retained as runtime diagnostic')
    selected_state=$sample3.state; selected_authority_sha256='authority'; selected_quorum_attempts=@(1,2,3); authority_outlier_attempts=@()
    runtime_listener=[ordered]@{{pid_drift_within_selected_quorum=$true}}
    samples=@($sample1,$sample2,$sample3)
}}
$changedState = New-TestState @(5000,16332)
$changedState.health.identity.release_version = 'changed'
$changedSample = [ordered]@{{attempt=1;usable=$true;state=$changedState}}
$changedWindow = [ordered]@{{
    verified=$true; reasons=@(); warnings=@(); selected_state=$changedState; selected_authority_sha256='changed-authority'
    selected_quorum_attempts=@(1,2); authority_outlier_attempts=@(); runtime_listener=[ordered]@{{pid_drift_within_selected_quorum=$false}}
    samples=@($changedSample)
}}
$comparison = New-HonghuProductionWindowComparison -Before $before -AfterWindow $window
$changed = New-HonghuProductionWindowComparison -Before $before -AfterWindow $changedWindow
$forbidden = New-HonghuProductionWindowComparison -Before $before -AfterWindow $window -ForbiddenListenerPids @(4604)
$missing = Test-HonghuProductionUnchanged -Before $before -After (New-TestState @())
[ordered]@{{comparison=$comparison;changed=$changed;forbidden=$forbidden;missing=$missing}} | ConvertTo-Json -Depth 30 -Compress
"""
            result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload["comparison"]["verified"], payload)
        self.assertFalse(payload["comparison"]["listener"]["pid_drift"])
        self.assertTrue(payload["comparison"]["runtime_listener_window"]["pid_drift_within_selected_quorum"])
        self.assertTrue(payload["comparison"]["warnings"])
        self.assertFalse(payload["changed"]["verified"])
        self.assertTrue(any("release_version" in x for x in payload["changed"]["reasons"]))
        self.assertFalse(payload["forbidden"]["verified"])
        self.assertTrue(payload["forbidden"]["forbidden_listener_observations"])
        self.assertFalse(payload["missing"]["verified"])
        self.assertTrue(any("listener was absent" in x for x in payload["missing"]["reasons"]))

    def test_production_pointer_and_manifest_changes_remain_fail_closed(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result_path = root / "comparison.json"
            script = rf"""
$ErrorActionPreference = 'Stop'
. '{helper}'
function Invoke-WebRequest {{
    param([switch]$UseBasicParsing, $Uri, $TimeoutSec, $ErrorAction)
    [pscustomobject]@{{ StatusCode = 200; Content = '{{"release_version":"legacy-1"}}' }}
}}
function Get-NetTCPConnection {{
    param($State, $LocalPort, $ErrorAction)
    [pscustomobject]@{{ OwningProcess = 4321; LocalPort = 8080 }}
}}
$before = Get-HonghuProductionState -Root '{temp}'
'new-current' | Set-Content -LiteralPath '{root / "current"}' -Encoding UTF8
'new-manifest' | Set-Content -LiteralPath '{root / "BROADCAST_MANIFEST.json"}' -Encoding UTF8
$after = Get-HonghuProductionState -Root '{temp}'
$comparison = Test-HonghuProductionUnchanged -Before $before -After $after
$comparison | ConvertTo-Json -Depth 12 -Compress | Set-Content -LiteralPath '{result_path}' -Encoding UTF8
"""
            result = _run_powershell(script)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(result_path.is_file(), result.stdout + result.stderr)
            # Windows PowerShell 5.1 writes a UTF-8 BOM while PowerShell 7 does
            # not. The contract under test is the comparison object, not the
            # console host's output transport or BOM policy.
            payload = json.loads(result_path.read_text(encoding="utf-8-sig"))
        self.assertFalse(payload["verified"], payload)
        self.assertFalse(payload["current_pointer_stable"])
        self.assertFalse(payload["broadcast_manifest_stable"])
        self.assertTrue(any("current pointer" in x for x in payload["reasons"]))
        self.assertTrue(any("broadcast manifest" in x for x in payload["reasons"]))

    def test_release_powershell_hashing_does_not_require_get_file_hash_module(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        deploy = ROOT / "tools/release/Deploy-ReadonlyCandidate.ps1"
        self.assertNotIn("Get-FileHash", helper.read_text(encoding="utf-8"))
        self.assertNotIn("Get-FileHash", deploy.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "identity.txt"
            source.write_bytes(b"honghu-release-identity")
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            script = rf"""
$ErrorActionPreference = 'Stop'
. '{helper}'
Get-HonghuFileSha256 -Path '{source}'
"""
            result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], expected)

    def test_gate_evidence_remains_immutable_when_cleanup_state_recovers(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        script = rf"""
. '{helper}'
$evidence = [ordered]@{{
    observed = [ordered]@{{}}
    post_state = $null
    gate = [ordered]@{{ evaluated = $false }}
    recovery = [ordered]@{{ captured = $false }}
    failure = [ordered]@{{ primary = [ordered]@{{ message = 'Production 8080/current evidence is not stable.' }} }}
}}
$gateTasks = [ordered]@{{ verified = $false; reason = 'gate task mismatch' }}
$gateProduction = [ordered]@{{ verified = $false; reasons = @('gate health transient') }}
$recoveryTasks = [ordered]@{{ verified = $true; reason = $null }}
$recoveryProduction = [ordered]@{{ verified = $true; reasons = @() }}
$badWindow = [ordered]@{{ selected_state = [ordered]@{{ marker = 'gate' }}; verified = $false; reasons = @('gate health transient') }}
$goodWindow = [ordered]@{{ selected_state = [ordered]@{{ marker = 'post-cleanup' }}; verified = $true; reasons = @() }}
Set-HonghuCandidateGateEvidence -Evidence $evidence -PostTasks ([ordered]@{{ marker = 'gate' }}) -PostProductionWindow $badWindow -TaskComparison $gateTasks -ProductionComparison $gateProduction
Set-HonghuCandidateRecoveryEvidence -Evidence $evidence -PostCleanupTasks ([ordered]@{{ marker = 'post-cleanup' }}) -PostCleanupProductionWindow $goodWindow -TaskComparison $recoveryTasks -ProductionComparison $recoveryProduction
$secondGateRejected = $false
try {{
    Set-HonghuCandidateGateEvidence -Evidence $evidence -PostTasks ([ordered]@{{ marker = 'overwrite' }}) -PostProductionWindow $goodWindow -TaskComparison $recoveryTasks -ProductionComparison $recoveryProduction
}}
catch {{ $secondGateRejected = $true }}
[ordered]@{{ evidence = $evidence; second_gate_rejected = $secondGateRejected }} | ConvertTo-Json -Depth 20 -Compress
"""
        result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        evidence = payload["evidence"]
        self.assertTrue(payload["second_gate_rejected"])
        self.assertFalse(
            evidence["gate"]["comparisons"][
                "production_8080_and_pointer_unchanged"
            ]["verified"]
        )
        self.assertEqual(evidence["post_state"]["production"]["marker"], "gate")
        self.assertTrue(
            evidence["recovery"]["comparisons_to_pre"][
                "production_8080_and_pointer_unchanged"
            ]["verified"]
        )
        self.assertEqual(
            evidence["recovery"]["post_cleanup_state"]["production"]["marker"],
            "post-cleanup",
        )
        self.assertEqual(
            evidence["failure"]["primary"]["message"],
            "Production 8080/current evidence is not stable.",
        )
        self.assertFalse(
            evidence["observed"]["production_8080_and_pointer_unchanged"][
                "verified"
            ]
        )

    def test_process_identity_tolerates_missing_optional_cim_path_with_other_evidence(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        command = (
            "python tools.release.cli serve-readonly-candidate "
            "launch123 " + "a" * 40 + " 18080"
        )
        expected_hash = hashlib.sha256(command.encode()).hexdigest()
        script = rf"""
. '{helper}'
function Get-Process {{ param($Id,$ErrorAction); [pscustomobject]@{{ Id=77; StartTime=[datetime]'2026-08-07T01:02:03Z' }} }}
function Get-CimInstance {{ param($ClassName,$Filter,$ErrorAction); [pscustomobject]@{{ CommandLine='{command}' }} }}
function Get-NetTCPConnection {{ param($State,$LocalPort,$ErrorAction); [pscustomobject]@{{OwningProcess=77;LocalPort=18080}} }}
function Invoke-RestMethod {{ param($Uri,$TimeoutSec,$ErrorAction); [pscustomobject]@{{ok=$true;viewer_mode='readonly_candidate';release=[pscustomobject]@{{commit_sha='{'a' * 40}'}};candidate_process=[pscustomobject]@{{pid=77;launch_id='launch123'}}}} }}
$record=[pscustomobject]@{{pid=77;start_time_utc='2026-08-07T01:02:03.0000000Z';executable_path=$null;command_line_sha256='{expected_hash}';launch_id='launch123';commit_sha='{'a' * 40}';manifest_sha256='{'b' * 64}';port=18080;candidate_root='D:\candidate'}}
$snapshot=Get-HonghuCandidateProcessObservation -ProcessId 77 -Port 18080
[ordered]@{{snapshot=$snapshot;identity=(Test-HonghuCandidateProcessIdentity -Record $record -Snapshot $snapshot -RequireStopAuthority)}} | ConvertTo-Json -Depth 12 -Compress
"""
        result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertIsNone(payload["snapshot"]["executable_path"])
        self.assertTrue(payload["identity"]["ok"], payload)
        self.assertIn("executable_path", payload["identity"]["unavailable_evidence"])
        self.assertIn("listener_owner", payload["identity"]["matched_evidence"])

    def test_process_identity_can_use_listener_and_health_when_cim_is_denied(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        executable = str(Path(sys.executable).resolve()).replace("'", "''")
        script = rf"""
. '{helper}'
function Get-Process {{ param($Id,$ErrorAction); [pscustomobject]@{{ Id=88; StartTime=[datetime]'2026-08-07T01:02:03Z'; Path='{executable}' }} }}
function Get-CimInstance {{ param($ClassName,$Filter,$ErrorAction); throw 'access denied' }}
function Get-NetTCPConnection {{ param($State,$LocalPort,$ErrorAction); [pscustomobject]@{{OwningProcess=88;LocalPort=18080}} }}
function Invoke-RestMethod {{ param($Uri,$TimeoutSec,$ErrorAction); [pscustomobject]@{{ok=$true;viewer_mode='readonly_candidate';release=[pscustomobject]@{{commit_sha='{'a' * 40}'}};candidate_process=[pscustomobject]@{{pid=88;launch_id='launch-denied'}}}} }}
$record=[pscustomobject]@{{pid=88;start_time_utc='2026-08-07T01:02:03.0000000Z';executable_path='{executable}';command_line_sha256=$null;launch_id='launch-denied';commit_sha='{'a' * 40}';manifest_sha256='{'b' * 64}';port=18080;candidate_root='D:\candidate'}}
$snapshot=Get-HonghuCandidateProcessObservation -ProcessId 88 -Port 18080
[ordered]@{{snapshot=$snapshot;identity=(Test-HonghuCandidateProcessIdentity -Record $record -Snapshot $snapshot -RequireStopAuthority)}} | ConvertTo-Json -Depth 12 -Compress
"""
        result = _run_powershell(script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(payload["snapshot"]["cim_query"]["query_succeeded"])
        self.assertTrue(payload["identity"]["ok"], payload)
        self.assertIn("command_line", payload["identity"]["unavailable_evidence"])
        self.assertIn("candidate_health", payload["identity"]["matched_evidence"])

    def test_verified_candidate_cleanup_stops_matching_process_and_releases_record(self):
        if os.name != "nt":
            self.skipTest("PowerShell process identity contract is Windows-specific")
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        commit = "a" * 40
        launch = "launch-cleanup"
        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "viewer_candidate_process.json"
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(60)",
                    "tools.release.cli",
                    "serve-readonly-candidate",
                    launch,
                    commit,
                    "18080",
                ]
            )
            try:
                capture = rf"""
. '{helper}'
function Get-NetTCPConnection {{ param($State,$LocalPort,$ErrorAction); return @() }}
function Invoke-RestMethod {{ param($Uri,$TimeoutSec,$ErrorAction); throw 'not listening' }}
Get-HonghuCandidateProcessObservation -ProcessId {child.pid} -Port 18080 | ConvertTo-Json -Depth 12 -Compress
"""
                capture_result = _run_powershell(capture)
                self.assertEqual(
                    capture_result.returncode,
                    0,
                    capture_result.stdout + capture_result.stderr,
                )
                snapshot = json.loads(capture_result.stdout.strip().splitlines()[-1])
                record.write_text(
                    json.dumps(
                        {
                            "pid": child.pid,
                            "start_time_utc": snapshot["start_time_utc"],
                            "executable_path": snapshot["executable_path"],
                            "command_line_sha256": snapshot["command_line_sha256"],
                            "launch_id": launch,
                            "commit_sha": commit,
                            "manifest_sha256": "b" * 64,
                            "port": 18080,
                            "candidate_root": str(Path(temp)),
                        }
                    ),
                    encoding="utf-8",
                )
                stop = rf"""
. '{helper}'
function Get-NetTCPConnection {{ param($State,$LocalPort,$ErrorAction); return @() }}
function Invoke-RestMethod {{ param($Uri,$TimeoutSec,$ErrorAction); throw 'not listening' }}
Stop-HonghuVerifiedCandidate -RecordPath '{record}' | ConvertTo-Json -Depth 12 -Compress
"""
                stop_result = _run_powershell(stop)
                self.assertEqual(stop_result.returncode, 0, stop_result.stdout + stop_result.stderr)
                outcome = json.loads(stop_result.stdout.strip().splitlines()[-1])
                self.assertEqual(outcome["status"], "verified-candidate-stopped")
                child.wait(timeout=10)
                self.assertFalse(record.exists())
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)

    def test_stale_candidate_record_is_archived_only_when_pid_and_port_are_absent(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        record_payload = {
            "pid": 5500,
            "start_time_utc": "2026-08-06T00:00:00.0000000Z",
            "executable_path": r"D:\candidate\python.exe",
            "command_line_sha256": "c" * 64,
            "launch_id": "launch-stale",
            "commit_sha": "d" * 40,
            "manifest_sha256": "e" * 64,
            "port": 18080,
            "candidate_root": r"D:\honghu-ai-research-candidate",
        }
        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "viewer_candidate_process.json"
            record.write_text(json.dumps(record_payload), encoding="utf-8")
            script = rf"""
. '{helper}'
function Get-Process {{ param($Id,$ErrorAction); return $null }}
function Get-CimInstance {{ param($ClassName,$Filter,$ErrorAction); return $null }}
function Get-NetTCPConnection {{ param($State,$LocalPort,$ErrorAction); return @() }}
function Invoke-RestMethod {{ param($Uri,$TimeoutSec,$ErrorAction); throw 'not listening' }}
Stop-HonghuVerifiedCandidate -RecordPath '{record}' | ConvertTo-Json -Depth 14 -Compress
"""
            result = _run_powershell(script)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["status"], "stale-record-archived")
            self.assertFalse(record.exists())
            archive = Path(payload["archive_path"])
            self.assertTrue(archive.is_file())
            archived = json.loads(archive.read_text(encoding="utf-8-sig"))
            self.assertEqual(archived["original_identity"]["pid"], 5500)
            self.assertEqual(archived["original_identity"]["launch_id"], "launch-stale")
            self.assertIn("no listener", archived["reason"])

    def test_stale_record_with_listener_conflict_remains_fail_closed(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        payload = {
            "pid": 5500,
            "start_time_utc": "2026-08-06T00:00:00Z",
            "executable_path": r"D:\candidate\python.exe",
            "command_line_sha256": "c" * 64,
            "launch_id": "launch-stale",
            "commit_sha": "d" * 40,
            "manifest_sha256": "e" * 64,
            "port": 18080,
            "candidate_root": r"D:\candidate",
        }
        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "viewer_candidate_process.json"
            record.write_text(json.dumps(payload), encoding="utf-8")
            script = rf"""
. '{helper}'
function Get-Process {{ param($Id,$ErrorAction); return $null }}
function Get-CimInstance {{ param($ClassName,$Filter,$ErrorAction); return $null }}
function Get-NetTCPConnection {{ param($State,$LocalPort,$ErrorAction); [pscustomobject]@{{OwningProcess=9900;LocalPort=18080}} }}
function Invoke-RestMethod {{ param($Uri,$TimeoutSec,$ErrorAction); throw 'wrong service' }}
Stop-HonghuVerifiedCandidate -RecordPath '{record}' | Out-Null
"""
            result = _run_powershell(script)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(record.is_file())
            self.assertFalse((Path(temp) / "stale_process_records").exists())

    def test_stale_record_with_reachable_health_is_not_archived(self):
        helper = ROOT / "tools/release/CandidateProcess.ps1"
        payload = {
            "pid": 5500,
            "start_time_utc": "2026-08-06T00:00:00Z",
            "executable_path": r"D:\candidate\python.exe",
            "command_line_sha256": "c" * 64,
            "launch_id": "launch-stale",
            "commit_sha": "d" * 40,
            "manifest_sha256": "e" * 64,
            "port": 18080,
            "candidate_root": r"D:\candidate",
        }
        with tempfile.TemporaryDirectory() as temp:
            record = Path(temp) / "viewer_candidate_process.json"
            record.write_text(json.dumps(payload), encoding="utf-8")
            script = rf"""
. '{helper}'
function Get-Process {{ param($Id,$ErrorAction); return $null }}
function Get-CimInstance {{ param($ClassName,$Filter,$ErrorAction); return $null }}
function Get-NetTCPConnection {{ param($State,$LocalPort,$ErrorAction); return @() }}
function Invoke-RestMethod {{ param($Uri,$TimeoutSec,$ErrorAction); [pscustomobject]@{{ok=$true}} }}
Stop-HonghuVerifiedCandidate -RecordPath '{record}' | Out-Null
"""
            result = _run_powershell(script)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(record.is_file())
            self.assertFalse((Path(temp) / "stale_process_records").exists())

    def test_failure_evidence_separates_primary_cleanup_and_production_comparison(self):
        deploy = (ROOT / "tools/release/Deploy-ReadonlyCandidate.ps1").read_text(
            encoding="utf-8"
        )
        helper = (ROOT / "tools/release/CandidateProcess.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("$evidence.failure.primary", deploy)
        self.assertIn("$evidence.failure.cleanup", deploy)
        self.assertIn("$evidence.failure.pointer_recovery", deploy)
        self.assertIn("$evidence.failure.final_state_capture", deploy)
        self.assertIn("$failurePostProductionWindow", deploy)
        self.assertIn("Set-HonghuCandidateGateEvidence", deploy)
        self.assertIn("Set-HonghuCandidateRecoveryEvidence", deploy)
        self.assertIn("honghu.vm_readonly_candidate_evidence.v6", deploy)
        self.assertIn("production_8080_and_pointer_unchanged", helper)
        catch_body = deploy[deploy.index("catch {\n    $primaryFailure") :]
        self.assertNotIn(
            "$evidence.observed.production_8080_and_pointer_unchanged = $failureProductionComparison",
            catch_body,
        )
        self.assertNotIn(
            "$evidence.post_state = [ordered]@{ scheduled_tasks = $failurePostTasks",
            catch_body,
        )
        self.assertLess(
            catch_body.index("$evidence.failure.primary"),
            catch_body.index("$evidence.failure.final_state_capture"),
        )
        self.assertLess(
            deploy.index(
                "Save-HonghuEvidenceDocument -Evidence $evidence",
                deploy.index("catch {\n    $primaryFailure"),
            ),
            deploy.index("throw $primaryFailure"),
        )


if __name__ == "__main__":
    unittest.main()
