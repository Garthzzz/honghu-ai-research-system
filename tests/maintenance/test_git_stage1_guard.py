from __future__ import annotations

from pathlib import Path

from tools.maintenance.git_stage1_guard import (
    build_inventory,
    check_sqlite_ratchet,
    classify,
    load_policy,
)


ROOT = Path(__file__).resolve().parents[2]


def test_only_the_pinned_public_certificate_is_an_allowed_binary() -> None:
    policy = load_policy(ROOT / "config" / "git_tracked_policy.json")

    approved, _ = classify(
        "config/migration/stage5_storage_attestation_public.cer", policy
    )
    unreviewed, _ = classify("config/migration/unreviewed.cer", policy)

    assert approved == "tracked_deployment_config_template"
    assert unreviewed == "pending_review"


def test_git_metadata_exclusion_does_not_hide_github_workflows(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("private", encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: test\n", encoding="utf-8")

    inventory = build_inventory(
        tmp_path,
        load_policy(ROOT / "config" / "git_tracked_policy.json"),
    )
    records = {row["path"]: row for row in inventory["records"]}

    assert ".git/config" not in records
    assert records[".github/workflows/ci.yml"]["classification"] == (
        "tracked_deployment_config_template"
    )


def test_requirements_input_files_are_tracked_sources(tmp_path: Path) -> None:
    (tmp_path / "requirements.in").write_text("Flask\n", encoding="utf-8")
    inventory = build_inventory(
        tmp_path,
        load_policy(ROOT / "config" / "git_tracked_policy.json"),
    )
    records = {row["path"]: row for row in inventory["records"]}

    assert records["requirements.in"]["classification"] == "tracked_source"


def test_local_virtual_environment_is_runtime_not_pending_review(tmp_path: Path) -> None:
    package = tmp_path / ".venv-stage1" / "Lib" / "site-packages" / "sample.py"
    package.parent.mkdir(parents=True)
    package.write_text("value = 1\n", encoding="utf-8")
    inventory = build_inventory(
        tmp_path,
        load_policy(ROOT / "config" / "git_tracked_policy.json"),
    )
    records = {row["path"]: row for row in inventory["records"]}

    assert records[".venv-stage1/Lib/site-packages/sample.py"]["classification"] == (
        "runtime"
    )


def test_sqlite_ratchet_only_accepts_complete_bounded_exception() -> None:
    current = {"counts_by_file_rule": {"tools/example.py": {"sqlite3_connect": 2}}}
    baseline = {
        "counts_by_file_rule": {},
        "documented_exceptions": [
            {
                "path": "tools/example.py",
                "rule": "sqlite3_connect",
                "max_count": 2,
                "domain": "release test fixture",
                "reason": "synthetic fixture only",
                "owner": "release governance",
                "future_cutover_unit_candidate": "dev/test data platform",
                "sunset_condition": "remove after the PostgreSQL dev fixture is authoritative",
            }
        ],
    }

    result = check_sqlite_ratchet(current, baseline)

    assert result["status"] == "pass"
    assert result["applied_exceptions"][0]["exception_limit"] == 2


def test_sqlite_ratchet_rejects_incomplete_or_exceeded_exception() -> None:
    current = {"counts_by_file_rule": {"tools/example.py": {"sqlite3_connect": 3}}}
    baseline = {
        "counts_by_file_rule": {},
        "documented_exceptions": [
            {
                "path": "tools/example.py",
                "rule": "sqlite3_connect",
                "max_count": 2,
                "domain": "release test fixture",
                "reason": "synthetic fixture only",
                "owner": "release governance",
                "future_cutover_unit_candidate": "dev/test data platform",
                "sunset_condition": "remove after the PostgreSQL dev fixture is authoritative",
            }
        ],
    }

    result = check_sqlite_ratchet(current, baseline)

    assert result["status"] == "blocked"
    assert result["failures"] == [
        {"path": "tools/example.py", "rule": "sqlite3_connect", "baseline": 2, "current": 3}
    ]
