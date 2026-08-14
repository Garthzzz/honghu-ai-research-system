from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tools.migration.stage4_user_content_writer_fence import (
    WriterFenceError,
    _sha,
    capture_sqlite_watermark,
    compile_writer_fence,
)


def _database(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE analyst_note(
          id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL,
          q_number TEXT, note_type TEXT, title TEXT, content TEXT NOT NULL,
          author TEXT, created_at TEXT, updated_at TEXT
        );
        INSERT INTO analyst_note(entity_type,entity_id,content,author)
        VALUES('company',330,'evidence','analyst');
        """
    )
    connection.commit()
    connection.close()
    return path


def _windows(**updates: object) -> dict:
    core = {
        "schema_version": "honghu.user_content_windows_fence.v1",
        "captured_at_utc": "2026-08-13T12:00:00Z",
        "preflight_query_succeeded": True,
        "legacy_health_was_reachable": True,
        "legacy_listener_identity_verified": True,
        "legacy_listener_stopped": True,
        "legacy_service_fence_verified": True,
        "post_stop_listener_absent": True,
        "post_stop_health_unreachable": True,
        "scheduled_task_query_succeeded": True,
        "process_query_succeeded": True,
        "stopped_listener_pids": [1234],
        "stopped_service_identities": [],
        "scheduled_writer_matches": [],
        "writer_process_matches": [],
    }
    core.update(updates)
    return {**core, "observation_sha256": _sha(core)}


def test_watermark_is_query_only_and_content_addressed(tmp_path: Path) -> None:
    database = _database(tmp_path / "research.db")
    before = database.read_bytes()
    watermark = capture_sqlite_watermark(database)
    assert watermark["analyst_note_count"] == 1
    assert watermark["max_id"] == 1
    assert watermark["quick_check"] == "ok"
    assert len(watermark["watermark_sha256"]) == 64
    assert database.read_bytes() == before


def test_fence_requires_stable_watermark_and_no_live_writer(tmp_path: Path) -> None:
    watermark = capture_sqlite_watermark(_database(tmp_path / "research.db"))
    result = compile_writer_fence(
        before=watermark, after=watermark, windows_observation=_windows(),
        application_commit_sha="a" * 40, release_manifest_sha256="b" * 64,
    )
    assert result["verified"] is True
    assert result["sqlite_writer_fenced"] is True
    assert result["sqlite_final_watermark"] == watermark

    changed = dict(watermark, analyst_note_count=2)
    with pytest.raises(WriterFenceError, match="watermark changed"):
        compile_writer_fence(
            before=watermark, after=changed, windows_observation=_windows(),
            application_commit_sha="a" * 40, release_manifest_sha256="b" * 64,
        )
    with pytest.raises(WriterFenceError, match="scheduled analyst-note writer"):
        compile_writer_fence(
            before=watermark,
            after=watermark,
            windows_observation=_windows(scheduled_writer_matches=[{"task": "bad"}]),
            application_commit_sha="a" * 40,
            release_manifest_sha256="b" * 64,
        )
    with pytest.raises(WriterFenceError, match="writer process"):
        compile_writer_fence(
            before=watermark,
            after=watermark,
            windows_observation=_windows(writer_process_matches=[{"pid": 7}]),
            application_commit_sha="a" * 40,
            release_manifest_sha256="b" * 64,
        )


def test_tampered_windows_observation_is_rejected(tmp_path: Path) -> None:
    watermark = capture_sqlite_watermark(_database(tmp_path / "research.db"))
    observation = _windows()
    observation["stopped_listener_pids"] = [9999]
    with pytest.raises(WriterFenceError, match="identity mismatch"):
        compile_writer_fence(
            before=watermark, after=watermark, windows_observation=observation,
            application_commit_sha="a" * 40, release_manifest_sha256="b" * 64,
        )


def test_powershell_contract_collects_before_and_after_without_task_mutation() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "tools/migration/Invoke-UserContentWriterFence.ps1").read_text(
        encoding="utf-8"
    )
    assert "Get-ScheduledTask" in source
    assert "Register-ScheduledTask" not in source
    assert "Set-ScheduledTask" not in source
    assert "sqlite_watermark_before_stop.json" in source
    assert "sqlite_watermark_after_stop.json" in source
    assert "legacy Viewer PID was reused before stop" in source
    assert "post_stop_listener_absent" in source
    assert "--expected-commit" in source
    assert "stage4_isolated_entry.py" in source
    assert "--module $Module -- capture" in source
    assert "[Parameter(Mandatory = $true)][string]$RepoRoot" in source
    assert "$Dispatcher = Join-Path $RepoRoot 'tools\\migration\\stage4_isolated_entry.py'" in source
    assert "--repo-root $RepoRoot" in source
    assert "--repo-root $ReleaseDir" not in source
    assert "(Join-Path $ReleaseDir 'RELEASE_MANIFEST.json')" in source
    assert "reviewed repository root and immutable release directory must be distinct" in source
    assert "Get-HonghuScheduledTaskActionInspection" in source
    assert "unsupportedRelevantActions" in source
    assert "Get-CimInstance Win32_Service" in source
    assert "Stop-Service -Name" in source
    assert "Start-Service -Name" in source
    assert "legacy_service_fence_verified" in source
    assert "$approvedFingerprints" in source
    assert "$approvedViewerProcesses" in source
    assert "viewer_pids = @()" in source
    assert "Merely containing ``tools.viewer.app`` is not sufficient" in source
    assert "legacy Viewer PID identity changed before stop" in source


def test_scheduled_task_action_inspection_handles_non_exec_actions(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    helper = root / "tools/migration/Stage4ScheduledTaskInspection.ps1"
    script = tmp_path / "task_action_probe.ps1"
    script.write_text(
        "\n".join(
            (
                "$ErrorActionPreference = 'Stop'",
                "Set-StrictMode -Version Latest",
                f". '{helper.as_posix()}'",
                "$nonExec = [pscustomobject]@{ Id = 'handler'; ClassId = 'abc' }",
                "$exec = [pscustomobject]@{ Execute = 'python.exe'; Arguments = '-m tools.viewer.app' }",
                "$a = Get-HonghuScheduledTaskActionInspection -Action $nonExec",
                "$b = Get-HonghuScheduledTaskActionInspection -Action $exec",
                "[ordered]@{ non_exec = $a; exec = $b } | ConvertTo-Json -Depth 5 -Compress",
            )
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(result.stdout)
    assert payload["non_exec"]["has_execute_property"] is False
    assert payload["non_exec"]["searchable_text"] == ""
    assert payload["non_exec"]["class_id"] == "abc"
    assert payload["exec"]["has_execute_property"] is True
    assert payload["exec"]["searchable_text"] == "python.exe -m tools.viewer.app"
