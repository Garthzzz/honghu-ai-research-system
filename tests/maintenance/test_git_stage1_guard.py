from __future__ import annotations

from pathlib import Path

from tools.maintenance.git_stage1_guard import build_inventory, load_policy


ROOT = Path(__file__).resolve().parents[2]


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
