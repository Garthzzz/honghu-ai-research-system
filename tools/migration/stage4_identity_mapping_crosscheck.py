from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

AUTO_LISTING_STATUSES = {
    "",
    "unlisted",
    "private",
    "subsidiary_or_brand",
    "private_subsidiary",
    "pre_ipo",
    "soe",
    "parent_subsidiary",
}


class IdentityCrosscheckError(RuntimeError):
    pass


def _canonical(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", text)


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise IdentityCrosscheckError(f"JSON object required: {path}")
    return payload


def _query_snapshot(path: Path, queries: dict[str, str]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        values = {
            name: [dict(row) for row in connection.execute(sql)]
            for name, sql in queries.items()
        }
        evidence = {
            "database": path.name,
            "transaction_contract": "one_explicit_query_only_transaction",
            "schema_version": int(connection.execute("PRAGMA schema_version").fetchone()[0]),
            "tables": {
                name: {"row_count": len(rows), "content_sha256": _sha(rows)}
                for name, rows in values.items()
            },
        }
        connection.rollback()
        evidence["snapshot_identity_sha256"] = _sha(evidence)
        return values, evidence
    finally:
        connection.close()


def build_crosscheck(
    *, mapping_path: Path, source_data_root: Path, output_path: Path
) -> dict[str, Any]:
    mapping = _load(mapping_path)
    if mapping.get("schema_version") != "honghu.user_content_identity_mapping.v3":
        raise IdentityCrosscheckError("identity mapping v3 is required")
    research_rows, research_evidence = _query_snapshot(
        source_data_root / "research.db",
        {"company": "SELECT id,name,ticker,market,listing_status FROM company"},
    )
    financial_rows, financial_evidence = _query_snapshot(
        source_data_root / "financial.db",
        {
            "financial_security": """
            SELECT research_company_id,canonical_name,ticker,market,
                   listing_status,identity_status
              FROM financial_security
            """
        },
    )
    sentiment_rows, sentiment_evidence = _query_snapshot(
        source_data_root / "sentiment.db",
        {"company_alias": "SELECT company_id,ticker,alias,alias_type FROM company_alias"},
    )
    database_evidence = {
        "research.db": research_evidence,
        "financial.db": financial_evidence,
        "sentiment.db": sentiment_evidence,
    }
    research_companies = {
        str(row["id"]): row for row in research_rows["company"]
    }
    financial = {
        str(row["research_company_id"]): row
        for row in financial_rows["financial_security"]
    }
    aliases = defaultdict(list)
    for row in sentiment_rows["company_alias"]:
        aliases[str(row["company_id"])].append(row)

    normalized_company_names = defaultdict(list)
    for legacy_id, row in research_companies.items():
        normalized_company_names[_canonical(row["name"])].append(legacy_id)
    normalized_alias_names = defaultdict(set)
    for legacy_id, records in aliases.items():
        for row in records:
            name = _canonical(row.get("alias"))
            if name:
                normalized_alias_names[name].add(legacy_id)

    fallback = [
        record
        for record in mapping.get("mappings") or []
        if record.get("entity_type") == "company"
        and record.get("basis") == "normalized_name_and_market_fallback"
    ]
    automatic = []
    manual = []
    for record in fallback:
        legacy_id = str(record["legacy_id"])
        source = research_companies.get(legacy_id)
        mirror = financial.get(legacy_id)
        reasons = []
        if source is None or mirror is None:
            reasons.append("missing_research_or_financial_identity")
        else:
            source_name = _canonical(source.get("name"))
            if source_name != _canonical(mirror.get("canonical_name")):
                reasons.append("canonical_name_mismatch")
            if str(mirror.get("identity_status") or "") != "verified":
                reasons.append("financial_identity_not_verified")
            if str(source.get("ticker") or "").strip() or str(mirror.get("ticker") or "").strip():
                reasons.append("unexpected_security_ticker")
            listing_status = _canonical(
                mirror.get("listing_status") or source.get("listing_status")
            )
            if listing_status not in AUTO_LISTING_STATUSES:
                reasons.append("listed_or_market_identity_without_ticker")
            if len(normalized_company_names[source_name]) != 1:
                reasons.append("canonical_name_collision")
            alias_owners = normalized_alias_names.get(source_name, set()) - {legacy_id}
            if alias_owners:
                reasons.append("name_collides_with_other_company_alias")
            alias_tickers = {
                str(item.get("ticker") or "").strip()
                for item in aliases.get(legacy_id, [])
                if str(item.get("ticker") or "").strip()
            }
            if alias_tickers:
                reasons.append("sentiment_alias_has_unresolved_ticker")
        item = {
            "legacy_id": legacy_id,
            "display_name": (source or {}).get("name"),
            "stable_key": record["stable_key"],
            "listing_status": (mirror or {}).get("listing_status"),
            "market": (mirror or {}).get("market"),
            "source_evidence_identity": record.get("source_evidence_identity"),
            "reasons": sorted(set(reasons)),
        }
        if reasons:
            manual.append(item)
        else:
            automatic.append(
                {
                    "legacy_id": legacy_id,
                    "stable_key": record["stable_key"],
                    "verification": "research-financial one-to-one verified canonical name; no ticker or cross-entity alias collision",
                    "source_evidence_identity": record.get("source_evidence_identity"),
                }
            )
    summary_core = {
        "schema_version": "honghu.identity_mapping_crosscheck.v1",
        "mapping_manifest_sha256": mapping["manifest_sha256"],
        "source_snapshot_identity_sha256": _sha(database_evidence),
        "database_snapshot_evidence": database_evidence,
        "counts": {
            "mapping_total": len(mapping.get("mappings") or []),
            "company_total": sum(
                1 for item in mapping.get("mappings") or [] if item.get("entity_type") == "company"
            ),
            "ticker_venue_direct": sum(
                1
                for item in mapping.get("mappings") or []
                if item.get("entity_type") == "company"
                and item.get("basis") != "normalized_name_and_market_fallback"
            ),
            "fallback_total": len(fallback),
            "fallback_machine_crosschecked": len(automatic),
            "fallback_requires_human": len(manual),
            "approved_alias_groups": len(mapping.get("alias_groups") or []),
            "identity_overrides": int(mapping.get("identity_override_count") or 0),
        },
        "manual_review_items": manual,
        "automatic_items_identity_sha256": _sha(automatic),
        "approval_contract": {
            "machine_crosscheck_is_not_cutover_approval": True,
            "codex_may_not_approve_final_mapping": True,
            "human_scope_is_manual_review_items_plus_bundle_level_approval": True,
        },
    }
    result = {**summary_core, "summary_sha256": _sha(summary_core)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--source-data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_crosscheck(
        mapping_path=args.mapping,
        source_data_root=args.source_data_root,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
