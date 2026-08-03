from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.maintenance.migrate_paper_paths import DATABASES, build_plan, execute
from tools.pipeline.paper_paths import (
    filesystem_path,
    paper_path_violations,
    proposed_paper_path,
)


def _empty_databases(root: Path) -> None:
    for relative in DATABASES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                "CREATE TABLE path_reference (source_path TEXT NOT NULL)"
            )


def test_existing_identical_safe_copy_is_deduplicated_and_references_move(
    tmp_path: Path,
) -> None:
    root = tmp_path / "industry_demo"
    papers = root / "papers" / "HDI"
    papers.mkdir(parents=True)
    source = papers / (("long-report-title-" * 9) + ".pdf")
    filesystem_path(source).write_bytes(b"%PDF-identical")
    target = proposed_paper_path(source, project_root=root)
    target.write_bytes(filesystem_path(source).read_bytes())
    _empty_databases(root)
    relative_source = source.relative_to(root).as_posix()
    with sqlite3.connect(root / DATABASES[0]) as conn:
        conn.execute(
            "INSERT INTO path_reference(source_path) VALUES (?)",
            (relative_source,),
        )
    config = root / "config"
    config.mkdir()
    reference = config / "paper.json"
    reference.write_text(relative_source, encoding="utf-8")

    plan = build_plan(root)
    rows = plan["rows"]

    assert len(rows) == 1
    assert rows[0].action == "deduplicate"

    backup = tmp_path / "industry_demo_paper_backup"
    result = execute(root, backup)

    assert result["status"] == "applied"
    assert result["remaining_violations"] == 0
    assert not source.exists()
    assert target.read_bytes() == b"%PDF-identical"
    assert paper_path_violations(root / "papers", project_root=root) == []
    assert reference.read_text(encoding="utf-8") == target.relative_to(
        root
    ).as_posix()
    with sqlite3.connect(root / DATABASES[0]) as conn:
        stored = conn.execute(
            "SELECT source_path FROM path_reference"
        ).fetchone()[0]
    assert stored == target.relative_to(root).as_posix()


def test_existing_different_target_is_not_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "industry_demo"
    papers = root / "papers"
    papers.mkdir(parents=True)
    source = papers / (("long-report-title-" * 9) + ".pdf")
    filesystem_path(source).write_bytes(b"%PDF-old")
    target = proposed_paper_path(source, project_root=root)
    target.write_bytes(b"%PDF-different")
    _empty_databases(root)

    try:
        build_plan(root)
    except FileExistsError as exc:
        message = str(exc)
    else:
        raise AssertionError("different target content must block migration")

    assert "内容不同" in message
    assert filesystem_path(source).read_bytes() == b"%PDF-old"
    assert target.read_bytes() == b"%PDF-different"
