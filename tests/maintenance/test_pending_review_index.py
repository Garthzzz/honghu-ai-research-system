from __future__ import annotations

from tools.maintenance.build_pending_review_index import build_index


def test_pending_index_is_stable_and_does_not_disclose_raw_paths() -> None:
    sensitive_path = "docs/private research title.md"
    result = build_index(
        {
            "records": [
                {
                    "path": sensitive_path,
                    "size": 42,
                    "classification": "pending_review",
                },
                {
                    "path": "tools/tracked.py",
                    "size": 7,
                    "classification": "tracked_source",
                },
            ]
        }
    )

    assert result["pending_count"] == 1
    assert result["records"][0]["scope"] == "docs"
    assert result["records"][0]["category"] == "legacy_or_diagnostic_document"
    assert sensitive_path not in str(result)
    assert result["records"][0]["safe_id"].startswith("pending:")
