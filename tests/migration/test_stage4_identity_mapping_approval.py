from __future__ import annotations

from tools.migration.stage4_identity_mapping_approval import build_approval_bundle


def test_approval_bundle_separates_direct_fallback_alias_and_override() -> None:
    snapshot_core = {
        "transaction_contract": {"mode": "explicit_read_transaction", "query_only": True},
        "database_pragmas": {},
        "source_tables": {},
    }
    mappings = [
        {
            "entity_type": "company",
            "legacy_id": "1",
            "stable_key": "company:security:ONE:venue:us",
            "basis": "normalized_ticker_and_venue",
            "source_evidence_identity": "1" * 64,
            "identity_components": {"ticker": "ONE", "venue": "us"},
            "review_identity": {"display_name": "One", "market": "US"},
        },
        {
            "entity_type": "company",
            "legacy_id": "2",
            "stable_key": "company:name-market:" + "2" * 64,
            "basis": "normalized_name_and_market_fallback",
            "source_evidence_identity": "2" * 64,
            "identity_components": {"ticker": None, "venue": None},
            "review_identity": {"display_name": "Two", "market": None},
        },
    ]
    core = {
        "schema_version": "honghu.user_content_identity_mapping.v3",
        "source_database": "fixture",
        "source_snapshot": {
            **snapshot_core,
            "snapshot_identity_sha256": __import__("hashlib").sha256(
                __import__("json").dumps(snapshot_core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "database_file_diagnostics": {"role": "diagnostic_only_not_transaction_snapshot_identity"},
        },
        "source_tables": {},
        "mappings": mappings,
        "collision_count": 0,
        "unapproved_alias_count": 0,
        "alias_approval_count": 0,
        "identity_override_count": 0,
        "alias_group_count": 0,
        "alias_groups": [],
    }
    manifest = {
        **core,
        "generated_at": "fixture",
        "manifest_sha256": __import__("hashlib").sha256(
            __import__("json").dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    bundle, summary = build_approval_bundle(manifest)
    assert summary["approval_status"] == "pending_user_cutover_approval"
    assert summary["cutover_level_approved"] is False
    assert summary["counts"]["ticker_and_venue_direct"] == 1
    assert summary["counts"]["name_and_market_fallback"] == 1
    assert bundle["direct_ticker_venue_items"][0]["display_name"] == "One"
    assert bundle["name_market_fallback_items"][0]["display_name"] == "Two"
