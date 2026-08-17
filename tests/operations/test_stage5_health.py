from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from tools.operations import stage5_health
from tools.release.direct_candidate import ALLOWED_MODULES


NOW = datetime(2026, 8, 17, 4, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def test_health_cli_is_exact_release_bootstrap_allowlisted() -> None:
    assert ALLOWED_MODULES["tools.operations.stage5_health"] == "main"


def healthy_components() -> dict[str, dict]:
    manifest = "c" * 64
    return {
        "viewer": {
            "ok": True,
            "reachable": True,
            "observed_commit_sha": SHA,
            "manifest_sha256": manifest,
        },
        "postgresql_authority": {
            "ok": True,
            "reachable": True,
            "runtime_catalog_commit_sha": SHA,
        },
        "production_tasks": {
            "ok": True,
            "process_model": "short_lived_scheduled_tick",
            "data_fresh": True,
            "task_count": 7,
            "exact_definition_identity_ok": True,
        },
        "backup_recovery": {
            "ok": True,
            "application_commit_sha": SHA,
            "verified_evidence_identity_sha256": "e" * 64,
        },
        "immutable_release": {
            "ok": True,
            "observed_commit_sha": SHA,
            "manifest_sha256": manifest,
        },
        "disk_capacity": {"ok": True},
    }


def test_aggregate_pass_keeps_process_and_freshness_separate() -> None:
    result = stage5_health.aggregate_stage5_health(healthy_components(), checked_at=NOW)
    assert result["status"] == "pass"
    assert result["process_state"]["viewer_reachable"] is True
    assert result["process_state"]["process_alive_is_not_data_freshness"] is True
    assert result["data_freshness"]["all_seven_tasks_fresh"] is True
    assert result["identity_binding"]["viewer_matches_verified_release"] is True
    assert result["identity_binding"]["postgres_runtime_matches_verified_release"] is True
    assert result["identity_binding"]["task_definitions_match_verified_release"] is True
    assert result["identity_binding"]["recovery_evidence_matches_verified_release"] is True
    assert len(result["identity_sha256"]) == 64
    assert result["alert"] == {
        "triggered": False,
        "delivery_mode": "local_machine_json_and_exit_status_only",
        "external_delivery_configured": False,
        "external_delivery_attempted": False,
    }


def test_alive_processes_do_not_hide_stale_data() -> None:
    components = healthy_components()
    components["production_tasks"]["ok"] = False
    components["production_tasks"]["data_fresh"] = False
    result = stage5_health.aggregate_stage5_health(components, checked_at=NOW)
    assert result["status"] == "blocked"
    assert result["process_state"]["viewer_reachable"] is True
    assert result["process_state"]["postgresql_reachable"] is True
    assert result["data_freshness"]["all_seven_tasks_fresh"] is False
    assert result["blocked_components"] == ["production_tasks"]
    assert result["alert"]["triggered"] is True


def test_missing_component_fails_closed() -> None:
    components = healthy_components()
    del components["backup_recovery"]
    result = stage5_health.aggregate_stage5_health(components, checked_at=NOW)
    assert result["status"] == "blocked"
    assert "backup_recovery" in result["blocked_components"]


def test_viewer_and_verified_release_manifest_must_match() -> None:
    components = healthy_components()
    components["viewer"]["manifest_sha256"] = "d" * 64
    result = stage5_health.aggregate_stage5_health(components, checked_at=NOW)
    assert result["status"] == "blocked"
    assert "runtime_release_identity_binding" in result["blocked_components"]


def test_probe_failure_does_not_copy_sensitive_exception_text() -> None:
    result = stage5_health._probe_failure(
        "postgresql_authority", RuntimeError("password=hunter2")
    )
    assert result["ok"] is False
    assert result["error_type"] == "RuntimeError"
    assert "hunter2" not in json.dumps(result)


def test_viewer_requires_exact_release_identity(monkeypatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, *_args):
            return json.dumps(
                {
                    "ok": True,
                    "release": {
                        "commit_sha": "b" * 40,
                        "manifest_sha256": "c" * 64,
                    },
                }
            ).encode()

    monkeypatch.setattr(stage5_health.urllib.request, "urlopen", lambda *a, **k: Response())
    result = stage5_health.probe_viewer(
        "http://127.0.0.1:8080/api/health",
        expected_commit_sha=SHA,
        timeout_seconds=1,
    )
    assert result["reachable"] is True
    assert result["application_ok"] is True
    assert result["ok"] is False


def test_viewer_probe_rejects_non_loopback_or_non_health_endpoint() -> None:
    for url in (
        "https://example.com/api/health",
        "http://127.0.0.1:8080/admin",
        "http://127.0.0.1:8443/api/health",
        "https://127.0.0.1:8080/api/health",
        "http://127.0.0.1:18080/api/health",
        "http://user@example.com/api/health",
        "http://127.0.0.1:8080/api/health?token=value",
    ):
        try:
            stage5_health.probe_viewer(
                url, expected_commit_sha=SHA, timeout_seconds=1
            )
        except stage5_health.Stage5HealthError:
            continue
        raise AssertionError(f"unsafe Viewer health URL accepted: {url}")


def test_runtime_component_commit_drift_blocks_identity_binding() -> None:
    components = healthy_components()
    components["postgresql_authority"]["runtime_catalog_commit_sha"] = "b" * 40
    result = stage5_health.aggregate_stage5_health(components, checked_at=NOW)
    assert result["status"] == "blocked"
    assert "runtime_release_identity_binding" in result["blocked_components"]
    assert result["identity_binding"]["postgres_runtime_matches_verified_release"] is False


def test_postgres_probe_requires_runtime_catalog_commit_binding(
    monkeypatch, tmp_path
) -> None:
    class Catalog:
        application_commit_sha = "b" * 40

    class Result:
        def fetchone(self):
            return ("honghu", "reader", True, False)

    class Connection:
        def execute(self, _sql):
            return Result()

        def close(self):
            return None

    class State:
        value = "S3"

    class Route:
        backend = stage5_health.Backend.POSTGRESQL_PRODUCTION
        authority_state = State()
        sqlite_writer_enabled = False
        writer_identity = "unit-writer"

    routes = {
        unit: Route() for unit in stage5_health.PRODUCTION_CUTOVER_UNITS
    }
    matrix = type(
        "Matrix",
        (),
        {
            "routes": routes,
            "health_payload": lambda self: {
                unit: {"state": "S3"} for unit in routes
            },
        },
    )()
    registry = type("Registry", (), {"registry_sha256": "c" * 64})()
    monkeypatch.setattr(stage5_health, "load_postgres_runtime_catalog", lambda _: Catalog())
    monkeypatch.setattr(
        stage5_health,
        "build_catalog_connection_factory",
        lambda *_a, **_k: Connection,
    )
    monkeypatch.setattr(
        stage5_health,
        "load_authority_matrix",
        lambda *_a, **_k: (registry, matrix),
    )

    result = stage5_health.probe_postgres_authority(
        tmp_path / "catalog.json",
        tmp_path / "registry.json",
        expected_commit_sha=SHA,
    )

    assert result["safe_postgresql_authority_unit_count"] == 9
    assert result["runtime_catalog_commit_matches_release"] is False
    assert result["ok"] is False


def test_recovery_probe_binds_canonical_identity_and_release(
    monkeypatch, tmp_path
) -> None:
    evidence = {
        "schema_version": "honghu.stage5_recovery_evidence.v1",
        "application_commit_sha": SHA,
        "wal_sync": {"verified": True},
    }
    evidence["identity_sha256"] = stage5_health.hashlib.sha256(
        json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path = tmp_path / "recovery.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(
        stage5_health,
        "evaluate_recovery_health",
        lambda *_a, **_k: {"status": "pass", "checks": [], "blockers": []},
    )

    result = stage5_health.probe_recovery(
        path,
        expected_commit_sha=SHA,
        max_wal_age_seconds=60,
        max_restore_age_seconds=60,
        max_full_scrub_age_seconds=60,
    )

    assert result["ok"] is True
    assert result["application_commit_sha"] == SHA
    assert result["verified_evidence_identity_sha256"] == evidence["identity_sha256"]


def test_recovery_probe_rejects_tamper_or_other_release(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        stage5_health,
        "evaluate_recovery_health",
        lambda *_a, **_k: {"status": "pass"},
    )
    for application_commit_sha, tamper in ((SHA, True), ("b" * 40, False)):
        evidence = {
            "application_commit_sha": application_commit_sha,
            "wal_sync": {"verified": True},
        }
        evidence["identity_sha256"] = stage5_health.hashlib.sha256(
            json.dumps(
                evidence,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if tamper:
            evidence["wal_sync"]["verified"] = False
        path = tmp_path / f"recovery-{application_commit_sha[0]}-{tamper}.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        try:
            stage5_health.probe_recovery(
                path,
                expected_commit_sha=SHA,
                max_wal_age_seconds=60,
                max_restore_age_seconds=60,
                max_full_scrub_age_seconds=60,
            )
        except stage5_health.Stage5HealthError:
            continue
        raise AssertionError("tampered or cross-release recovery evidence was accepted")


def test_aggregate_canonicalizes_real_task_health_datetimes() -> None:
    components = healthy_components()
    components["production_tasks"]["tasks"] = [
        {
            "task_id": "IndustryDemo_DynamicTick",
            "finished_at": NOW,
            "last_success_at": NOW,
        }
    ]

    result = stage5_health.aggregate_stage5_health(components, checked_at=NOW)

    observed = result["components"]["production_tasks"]["tasks"][0]
    assert observed["finished_at"] == NOW.isoformat()
    assert observed["last_success_at"] == NOW.isoformat()
    json.dumps(result)


def test_task_health_requires_exact_release_definition_identity(monkeypatch, tmp_path) -> None:
    task_manifest = type(
        "Manifest",
        (),
        {"sha256": "d" * 64, "runner_host": "DESKTOP-VGD07J4"},
    )()
    monkeypatch.setattr(stage5_health, "load_task_manifest", lambda _: task_manifest)
    monkeypatch.setattr(
        stage5_health,
        "task_health",
        lambda *a, **k: {
            "all_identity_ok": True,
            "all_enabled_and_fresh": True,
            "task_count": 7,
            "tasks": [
                {
                    "manifest_sha256": "d" * 64,
                    "application_commit_sha": "b" * 40,
                    "runner_host": "DESKTOP-VGD07J4",
                }
                for _ in range(7)
            ],
        },
    )
    result = stage5_health.probe_task_freshness(
        tmp_path / "tasks.json",
        tmp_path / "catalog.json",
        expected_commit_sha=SHA,
    )
    assert result["data_fresh"] is True
    assert result["exact_definition_identity_ok"] is False
    assert result["ok"] is False


def test_disk_probe_checks_both_absolute_and_percentage_thresholds(monkeypatch, tmp_path) -> None:
    usage = type("Usage", (), {"total": 1000, "used": 950, "free": 50})()
    monkeypatch.setattr(stage5_health.shutil, "disk_usage", lambda _: usage)
    result = stage5_health.probe_disk_capacity(
        [tmp_path], min_free_bytes=40, min_free_percent=10.0
    )
    assert result["ok"] is False
    assert result["paths"][0]["free_percent"] == 5.0


def test_collect_continues_after_one_probe_failure(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    def fail_viewer(*args, **kwargs):
        calls.append("viewer")
        raise OSError("network detail must not be returned")

    monkeypatch.setattr(stage5_health, "probe_viewer", fail_viewer)
    monkeypatch.setattr(
        stage5_health,
        "probe_postgres_authority",
        lambda *a, **k: calls.append("postgresql_authority") or {"ok": True, "reachable": True},
    )
    monkeypatch.setattr(
        stage5_health,
        "probe_task_freshness",
        lambda *a, **k: calls.append("production_tasks") or {"ok": True, "data_fresh": True},
    )
    monkeypatch.setattr(
        stage5_health,
        "probe_recovery",
        lambda *a, **k: calls.append("backup_recovery") or {"ok": True},
    )
    monkeypatch.setattr(
        stage5_health,
        "probe_release",
        lambda *a, **k: calls.append("immutable_release") or {"ok": True},
    )
    monkeypatch.setattr(
        stage5_health,
        "probe_disk_capacity",
        lambda *a, **k: calls.append("disk_capacity") or {"ok": True},
    )
    args = argparse.Namespace(
        viewer_health_url="http://127.0.0.1:8080/api/health",
        expected_commit_sha=SHA,
        http_timeout_seconds=1.0,
        postgres_runtime_catalog=tmp_path / "catalog.json",
        cutover_unit_registry=tmp_path / "registry.json",
        task_manifest=tmp_path / "tasks.json",
        recovery_evidence=tmp_path / "recovery.json",
        max_wal_age_seconds=60,
        max_restore_age_seconds=60,
        max_full_scrub_age_seconds=60,
        release_dir=tmp_path / "release",
        disk_path=[tmp_path],
        min_free_bytes=1,
        min_free_percent=1.0,
    )
    result = stage5_health.collect_stage5_health(args)
    assert calls == [
        "viewer",
        "postgresql_authority",
        "production_tasks",
        "backup_recovery",
        "immutable_release",
        "disk_capacity",
    ]
    assert result["status"] == "blocked"
    assert result["components"]["viewer"]["error_type"] == "OSError"


def test_cli_blocked_result_returns_two_and_writes_machine_readable_json(
    monkeypatch, tmp_path, capsys
) -> None:
    result = stage5_health.aggregate_stage5_health(
        {**healthy_components(), "disk_capacity": {"ok": False}}, checked_at=NOW
    )
    monkeypatch.setattr(stage5_health, "collect_stage5_health", lambda _: result)
    output = tmp_path / "health.json"
    argv = [
        "--viewer-health-url", "http://127.0.0.1:8080/api/health",
        "--postgres-runtime-catalog", str(tmp_path / "catalog.json"),
        "--cutover-unit-registry", str(tmp_path / "registry.json"),
        "--task-manifest", str(tmp_path / "tasks.json"),
        "--recovery-evidence", str(tmp_path / "recovery.json"),
        "--release-dir", str(tmp_path / "release"),
        "--expected-commit-sha", SHA,
        "--disk-path", str(tmp_path),
        "--max-wal-age-seconds", "60",
        "--max-restore-age-seconds", "60",
        "--output", str(output),
    ]
    assert stage5_health.main(argv) == 2
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "blocked"
    assert json.loads(capsys.readouterr().out)["alert"]["triggered"] is True


def test_cli_rejects_runtime_evidence_or_output_inside_release(
    monkeypatch, tmp_path
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    monkeypatch.setattr(
        stage5_health,
        "collect_stage5_health",
        lambda _: stage5_health.aggregate_stage5_health(
            healthy_components(), checked_at=NOW
        ),
    )
    common = [
        "--viewer-health-url", "http://127.0.0.1:8080/api/health",
        "--postgres-runtime-catalog", str(tmp_path / "catalog.json"),
        "--cutover-unit-registry", str(tmp_path / "registry.json"),
        "--task-manifest", str(tmp_path / "tasks.json"),
        "--release-dir", str(release),
        "--expected-commit-sha", SHA,
        "--disk-path", str(tmp_path),
        "--max-wal-age-seconds", "60",
        "--max-restore-age-seconds", "60",
    ]
    try:
        stage5_health.main(
            common
            + [
                "--recovery-evidence", str(release / "fake.json"),
                "--output", str(tmp_path / "health.json"),
            ]
        )
    except stage5_health.Stage5HealthError:
        pass
    else:
        raise AssertionError("recovery evidence inside immutable release was accepted")
    try:
        stage5_health.main(
            common
            + [
                "--recovery-evidence", str(tmp_path / "recovery.json"),
                "--output", str(release / "health.json"),
            ]
        )
    except stage5_health.Stage5HealthError:
        pass
    else:
        raise AssertionError("health output inside immutable release was accepted")
