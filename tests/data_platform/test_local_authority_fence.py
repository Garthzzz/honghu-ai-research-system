from __future__ import annotations

import json

import pytest

from tools.data_platform.local_authority_fence import (
    LocalAuthorityFenceError,
    assert_sqlite_write_allowed,
    authority_fence_path,
    load_authority_fence,
    write_authority_fence,
)


def _write(tmp_path, *, state: str, backend: str) -> None:
    path = authority_fence_path(tmp_path, "shared_identity")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "honghu.local_authority_fence.v1",
                "cutover_unit": "shared_identity",
                "authority_state": state,
                "authoritative_backend": backend,
                "authority_evidence_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )


def test_missing_or_s1_fence_allows_current_sqlite_writer(tmp_path) -> None:
    assert load_authority_fence(tmp_path, "shared_identity") is None
    assert_sqlite_write_allowed(tmp_path, "shared_identity")
    _write(tmp_path, state="S1", backend="sqlite_transition")
    assert_sqlite_write_allowed(tmp_path, "shared_identity")


@pytest.mark.parametrize("state", ["S2_PENDING", "S2", "S3", "S4"])
def test_postgresql_authority_marker_fences_stale_sqlite_writer(tmp_path, state) -> None:
    _write(tmp_path, state=state, backend="postgresql_production")
    with pytest.raises(LocalAuthorityFenceError, match="SQLite writer is retired"):
        assert_sqlite_write_allowed(tmp_path, "shared_identity")


def test_malformed_or_inconsistent_fence_fails_closed(tmp_path) -> None:
    _write(tmp_path, state="S3", backend="sqlite_transition")
    with pytest.raises(LocalAuthorityFenceError, match="invalid backend"):
        assert_sqlite_write_allowed(tmp_path, "shared_identity")


def test_atomic_fence_writer_round_trips_blocking_authority(tmp_path) -> None:
    path = write_authority_fence(
        tmp_path,
        cutover_unit="shared_identity",
        authority_state="S3",
        authoritative_backend="postgresql_production",
        authority_evidence_sha256="b" * 64,
        approval_reference="user-approval",
        cutover_epoch="shared-epoch",
    )
    assert path.is_file()
    assert load_authority_fence(tmp_path, "shared_identity")["cutover_epoch"] == "shared-epoch"
    with pytest.raises(LocalAuthorityFenceError, match="SQLite writer is retired"):
        assert_sqlite_write_allowed(tmp_path, "shared_identity")
