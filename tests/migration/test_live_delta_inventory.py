from __future__ import annotations

import subprocess
from pathlib import Path

from tools.migration.live_delta_inventory import (
    build_aggregate_manifest,
    build_live_only_addendum,
)
from tools.migration.sqlite_inventory import scan_file


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_live_only_addendum_excludes_tracked_and_never_embeds_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    live = tmp_path / "live"
    tracked = repo / "tools" / "tracked.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("import sqlite3\nsqlite3.connect('research.db')\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", "tools/tracked.py")
    _git(repo, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "init")

    (live / "tools").mkdir(parents=True)
    (live / "tools" / "tracked.py").write_text(tracked.read_text(encoding="utf-8"), encoding="utf-8")
    live_only = live / "tools" / "one_off.py"
    live_only.write_text(
        "import sqlite3\n"
        "def publish(conn):\n"
        "    conn.execute(\"INSERT INTO research_claim(id) VALUES (1)\")\n",
        encoding="utf-8",
    )
    secret = live / "tools" / "dynamic" / "secrets" / "credential.py"
    secret.parent.mkdir(parents=True)
    secret.write_text("TOKEN = 'must-not-appear'", encoding="utf-8")
    deployable_record = scan_file(repo, tracked)
    assert deployable_record is not None
    deployable = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip(),
        "inventory_sha256": "a" * 64,
        "files": [deployable_record],
    }

    addendum = build_live_only_addendum(
        live,
        repo,
        deployable,
        generated_at="2026-08-10T00:00:00+00:00",
    )

    assert [record["path"] for record in addendum["files"]] == ["tools/one_off.py"]
    assert addendum["summary"]["writer_operation_count"] == 1
    assert "must-not-appear" not in str(addendum)
    assert "INSERT INTO" not in str(addendum)


def test_aggregate_rejects_overlapping_paths() -> None:
    record = {
        "path": "tools/same.py",
        "lifecycle": "active_or_callable",
        "access": "read",
        "writer_operations": [],
        "transaction_boundaries": [],
        "attach_present": False,
        "domain": "other",
        "candidate_cutover_unit": "other",
    }
    deployable = {
        "source_commit": "b" * 40,
        "inventory_sha256": "c" * 64,
        "files": [record],
    }
    addendum = {
        "generated_at": "2026-08-10T00:00:00+00:00",
        "addendum_sha256": "d" * 64,
        "files": [dict(record)],
    }

    aggregate = build_aggregate_manifest(
        deployable,
        addendum,
        known_cutover_units={"other"},
    )

    assert aggregate["validation"]["passed"] is False
    assert aggregate["validation"]["path_overlap"] == ["tools/same.py"]


def test_aggregate_rejects_unknown_live_only_candidate_owner() -> None:
    live_record = {
        "path": "tools/live_only.py",
        "lifecycle": "active_or_callable",
        "access": "write",
        "writer_operations": [
            {
                "operation_id": "tools/live_only.py:publish:dml:4:0",
                "operation": "publish",
            }
        ],
        "transaction_boundaries": ["tools/live_only.py:publish"],
        "attach_present": False,
        "domain": "research",
        "candidate_cutover_unit": "missing_unit",
    }
    deployable = {
        "source_commit": "b" * 40,
        "inventory_sha256": "c" * 64,
        "files": [],
    }
    addendum = {
        "generated_at": "2026-08-10T00:00:00+00:00",
        "addendum_sha256": "d" * 64,
        "files": [live_record],
    }

    aggregate = build_aggregate_manifest(
        deployable,
        addendum,
        known_cutover_units={"research_publication"},
    )

    assert aggregate["validation"]["passed"] is False
    assert aggregate["validation"]["unknown_live_only_candidate_owners"] == [
        "missing_unit"
    ]
