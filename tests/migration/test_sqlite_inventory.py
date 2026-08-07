from pathlib import Path

from tools.migration.cutover_registry import build_registry
from tools.migration.sqlite_inventory import scan_file


def test_scan_file_assigns_operation_level_writer_and_attach(tmp_path: Path) -> None:
    source = tmp_path / "tools" / "pipeline" / "bridge.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """import sqlite3

def mutate(conn):
    conn.execute("ATTACH DATABASE ? AS financial", ('financial.db',))
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("INSERT OR REPLACE INTO financial_security(id) VALUES (1)")
""",
        encoding="utf-8",
    )

    result = scan_file(tmp_path, source)

    assert result is not None
    assert result["access"] == "write"
    assert result["attach_present"] is True
    assert result["transaction_boundaries"] == ["tools/pipeline/bridge.py:mutate"]
    assert {item["operation"] for item in result["writer_operations"]} == {"mutate"}


def test_registry_rejects_duplicate_object_ownership() -> None:
    ownership = {
        "states": {"current": "S0", "authoritative_backend": "sqlite_transition"},
        "boundary_change_policy": "human_review_required",
        "units": {
            "one": {"owner": "a", "risk": "low", "objects": {"research.db": ["x"]}},
            "two": {"owner": "b", "risk": "low", "objects": {"research.db": ["x"]}},
        },
    }
    inventory = {"source_commit": "a" * 40, "inventory_sha256": "b" * 64, "files": []}
    live = {"databases": {"research.db": {"tables": [{"name": "x"}]}}}

    registry = build_registry(ownership, inventory, live)

    assert registry["validation"]["passed"] is False
    assert registry["validation"]["ownership_conflicts"]


def test_registry_requires_every_live_table_to_have_one_owner() -> None:
    ownership = {
        "states": {"current": "S0", "authoritative_backend": "sqlite_transition"},
        "boundary_change_policy": "human_review_required",
        "units": {
            "one": {"owner": "a", "risk": "low", "objects": {"research.db": ["x"]}},
        },
    }
    inventory = {"source_commit": "a" * 40, "inventory_sha256": "b" * 64, "files": []}
    live = {"databases": {"research.db": {"tables": [{"name": "x"}, {"name": "y"}]}}}

    registry = build_registry(ownership, inventory, live)

    assert registry["validation"]["unowned_live_tables"] == [
        {"database": "research.db", "object": "y"}
    ]
