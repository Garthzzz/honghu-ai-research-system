from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.migration.stage4_identity_mapping import IdentityMappingResolver


def _sha(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_approval_bundle(mapping: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    IdentityMappingResolver(mapping)
    companies = [item for item in mapping.get("mappings") or [] if item.get("entity_type") == "company"]
    direct = []
    fallback = []
    overrides = []
    for item in companies:
        review = item.get("review_identity") or {}
        components = item.get("identity_components") or {}
        record = {
            "legacy_id": item["legacy_id"],
            "display_name": review.get("display_name"),
            "ticker": components.get("ticker"),
            "venue": components.get("venue"),
            "market": review.get("market"),
            "stable_key": item["stable_key"],
            "basis": item["basis"],
            "source_evidence_identity": item["source_evidence_identity"],
        }
        if item["basis"] == "normalized_name_and_market_fallback":
            fallback.append(record)
        else:
            direct.append(record)
        if item.get("identity_override"):
            overrides.append({**record, "identity_override": item["identity_override"]})

    full_core = {
        "schema_version": "honghu.identity_mapping_approval_bundle.v1",
        "mapping_manifest_sha256": mapping["manifest_sha256"],
        "snapshot_identity_sha256": mapping["source_snapshot"]["snapshot_identity_sha256"],
        "approval_status": "pending_user_cutover_approval",
        "cutover_level_approved": False,
        "approval_reference": None,
        "counts": {
            "total": len(mapping.get("mappings") or []),
            "company": len(companies),
            "ticker_and_venue_direct": len(direct),
            "name_and_market_fallback": len(fallback),
            "industry": sum(item.get("entity_type") == "industry" for item in mapping.get("mappings") or []),
            "industry_q": sum(item.get("entity_type") == "industry_q" for item in mapping.get("mappings") or []),
            "theme": sum(item.get("entity_type") == "theme" for item in mapping.get("mappings") or []),
        },
        "direct_ticker_venue_items": direct,
        "name_market_fallback_items": fallback,
        "approved_alias_groups": mapping.get("alias_groups") or [],
        "reviewed_identity_overrides": overrides,
    }
    bundle = {
        **full_core,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "bundle_sha256": _sha(full_core),
    }
    summary_core = {
        "schema_version": "honghu.identity_mapping_approval_summary.v1",
        "mapping_manifest_sha256": mapping["manifest_sha256"],
        "snapshot_identity_sha256": mapping["source_snapshot"]["snapshot_identity_sha256"],
        "approval_bundle_sha256": bundle["bundle_sha256"],
        "approval_status": "pending_user_cutover_approval",
        "cutover_level_approved": False,
        "counts": full_core["counts"],
        "direct_venue_distribution": dict(sorted(Counter(item["venue"] or "unresolved" for item in direct).items())),
        "fallback_market_distribution": dict(sorted(Counter(item["market"] or "empty" for item in fallback).items())),
        "approved_alias_groups": mapping.get("alias_groups") or [],
        "reviewed_identity_overrides": overrides,
        "review_contract": {
            "direct_items_location": "Git-excluded approval bundle: direct_ticker_venue_items",
            "fallback_items_location": "Git-excluded approval bundle: name_market_fallback_items",
            "codex_may_not_approve": True,
        },
    }
    summary = {**summary_core, "summary_sha256": _sha(summary_core)}
    return bundle, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a human-reviewable Stage 4 mapping approval bundle")
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--bundle-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    bundle, summary = build_approval_bundle(mapping)
    for path, payload in ((args.bundle_output, bundle), (args.summary_output, summary)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bundle_sha256": bundle["bundle_sha256"], "summary_sha256": summary["summary_sha256"], "approval_status": summary["approval_status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
