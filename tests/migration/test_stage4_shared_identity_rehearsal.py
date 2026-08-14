from __future__ import annotations

from pathlib import Path


def test_shared_identity_rehearsal_is_explicitly_isolated_and_fail_closed() -> None:
    source = (
        Path(__file__).parents[2]
        / "tools/migration/stage4_shared_identity_rehearsal.py"
    ).read_text(encoding="utf-8")
    assert "isolated_rehearsal_only" in source
    assert "wrong_writer_rejected" in source
    assert "conflicting_replay_rejected" in source
    assert "idempotent activation replay changed result" in source
    assert "shared_identity is not a reconciled S1 target" in source
    assert "first formal activation was not atomic with S3" in source
