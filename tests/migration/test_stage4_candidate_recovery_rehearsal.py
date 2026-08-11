from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.migration.stage4_candidate_recovery_rehearsal import (
    physical_memory_bytes,
    tree_identity,
    validate_candidate_target,
)


def test_physical_memory_probe_returns_real_positive_capacity() -> None:
    assert physical_memory_bytes() > 1024 * 1024


def test_candidate_target_rejects_production_and_viewer_ports(tmp_path) -> None:
    for port in (5432, 8080, 18080):
        with pytest.raises(ValueError):
            validate_candidate_target("127.0.0.1", port, tmp_path / "candidate")
    with pytest.raises(ValueError):
        validate_candidate_target("10.0.0.1", 55434, tmp_path / "candidate")


def test_candidate_target_rejects_live_application_data(tmp_path) -> None:
    root = tmp_path / "candidate"
    (root / "data").mkdir(parents=True)
    (root / "data" / "research.db").write_bytes(b"not-live-but-shaped-like-live")
    with pytest.raises(ValueError, match="live application data"):
        validate_candidate_target("127.0.0.1", 55434, root)


def test_tree_identity_binds_relative_paths_sizes_and_content(tmp_path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_text("one", encoding="utf-8")
    first = tree_identity(tmp_path)
    assert len(first) == 64
    (tmp_path / "a" / "one.txt").write_text("two", encoding="utf-8")
    assert tree_identity(tmp_path) != first
    assert hashlib.sha256(b"two").hexdigest() != first
