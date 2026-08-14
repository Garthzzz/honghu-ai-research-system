from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ENTITY_TABLES = ("company", "industry", "theme")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALIAS_APPROVALS = ROOT / "config/migration/stage4_identity_mapping_approvals.json"

TICKER_SUFFIX_VENUES = {
    "SH": "shanghai",
    "SZ": "shenzhen",
    "BJ": "beijing",
    "HK": "hong-kong",
    "T": "tokyo",
    "KS": "korea-main",
    "KQ": "korea-kosdaq",
    "TW": "taiwan-main",
    "TWO": "taiwan-otc",
    "VI": "vienna",
    "DE": "germany",
    "ST": "stockholm",
}
MARKET_VENUES = {
    "美股": "us",
    "美国": "us",
    "us": "us",
    "港股": "hong-kong",
    "香港": "hong-kong",
}
LISTING_STATUS_VENUES = {"us": "us", "hk": "hong-kong"}
SECURITY_STABLE_KEY_RE = re.compile(
    r"^company:security:(?P<ticker>.+):venue:(?P<venue>[^:]+)$"
)


class IdentityMappingError(RuntimeError):
    pass


class IdentityMappingResolver:
    def __init__(self, manifest: dict[str, Any]):
        core = {
            key: value
            for key, value in manifest.items()
            if key not in {"generated_at", "manifest_sha256"}
        }
        if manifest.get("schema_version") not in {
            "honghu.user_content_identity_mapping.v2",
            "honghu.user_content_identity_mapping.v3",
        }:
            raise IdentityMappingError("unsupported identity mapping schema")
        if manifest.get("manifest_sha256") != _sha(core):
            raise IdentityMappingError("identity mapping manifest hash mismatch")
        if manifest.get("schema_version") == "honghu.user_content_identity_mapping.v3":
            snapshot = manifest.get("source_snapshot") or {}
            snapshot_core = {
                "transaction_contract": snapshot.get("transaction_contract"),
                "database_pragmas": snapshot.get("database_pragmas"),
                "source_tables": manifest.get("source_tables"),
            }
            if snapshot.get("snapshot_identity_sha256") != _sha(snapshot_core):
                raise IdentityMappingError("identity mapping snapshot identity mismatch")
        self.manifest_sha256 = str(manifest["manifest_sha256"])
        self._by_legacy: dict[tuple[str, str], str] = {}
        for record in manifest.get("mappings") or []:
            key = (str(record["entity_type"]), str(record["legacy_id"]))
            stable_key = str(record["stable_key"])
            if key in self._by_legacy and self._by_legacy[key] != stable_key:
                raise IdentityMappingError(f"legacy identity maps to multiple stable keys: {key}")
            self._by_legacy[key] = stable_key

    @classmethod
    def from_path(cls, path: str | Path) -> "IdentityMappingResolver":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def resolve(self, entity_type: str, legacy_id: str | int) -> str:
        key = (str(entity_type), str(legacy_id))
        try:
            return self._by_legacy[key]
        except KeyError as exc:
            raise IdentityMappingError(
                f"unmapped user-content dependency: {key[0]}:{key[1]}"
            ) from exc


def mapping_snapshot_identity(manifest: dict[str, Any]) -> str:
    """Return the v3 snapshot identity without accepting an unbound alias.

    Early Stage 4 call sites incorrectly looked for a top-level
    ``snapshot_identity_sha256`` even though v3 stores it under
    ``source_snapshot``.  Keep the lookup in one place so approval checks bind
    the artifact that :class:`IdentityMappingResolver` actually validates.
    """

    snapshot = manifest.get("source_snapshot") or {}
    value = str(snapshot.get("snapshot_identity_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise IdentityMappingError("identity mapping snapshot identity is missing")
    return value


def mapping_semantic_core(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the stable business identity of an approved mapping.

    Absolute paths, whole-file hashes and SQLite ``schema_version`` are
    diagnostics of a particular physical file.  SQLite's online backup API can
    legitimately change those values while preserving every table definition
    and row.  They therefore cannot be the authority for whether a reviewed
    mapping still describes the same business identities.

    The semantic core remains fail-closed on the mapping algorithm contract,
    relevant database pragmas, table schemas/content, every mapping row and all
    explicit alias/override decisions.
    """

    IdentityMappingResolver(manifest)
    snapshot = manifest.get("source_snapshot") or {}
    pragmas = snapshot.get("database_pragmas") or {}
    return {
        "mapping_schema_version": manifest.get("schema_version"),
        "transaction_contract": snapshot.get("transaction_contract"),
        "database_pragmas": {
            "application_id": pragmas.get("application_id"),
            "user_version": pragmas.get("user_version"),
        },
        "source_tables": manifest.get("source_tables"),
        "mappings": manifest.get("mappings"),
        "collision_count": manifest.get("collision_count"),
        "unapproved_alias_count": manifest.get("unapproved_alias_count"),
        "alias_approval_count": manifest.get("alias_approval_count"),
        "identity_override_count": manifest.get("identity_override_count"),
        "alias_group_count": manifest.get("alias_group_count"),
        "alias_groups": manifest.get("alias_groups"),
    }


def mapping_semantic_identity(manifest: dict[str, Any]) -> str:
    return _sha(mapping_semantic_core(manifest))


def _canonical_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", text)


def _sha(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_identity_approvals(
    path: str | Path | None,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    if path is None:
        return {}, {}
    approval_path = Path(path).resolve()
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") not in {
        "honghu.identity_alias_approvals.v1",
        "honghu.identity_mapping_approvals.v2",
    }:
        raise IdentityMappingError("unsupported identity mapping approval schema")
    approval_file_sha256 = _file_sha(approval_path)
    approvals: dict[tuple[str, str], dict[str, Any]] = {}
    claimed_legacy: set[tuple[str, str]] = set()
    for item in payload.get("aliases") or []:
        entity_type = str(item.get("entity_type") or "").strip()
        stable_key = str(item.get("stable_key") or "").strip()
        legacy_ids = sorted({str(value).strip() for value in item.get("legacy_ids") or []})
        if entity_type != "company" or not stable_key or len(legacy_ids) < 2:
            raise IdentityMappingError("alias approval must identify one company stable key and at least two legacy ids")
        for field in ("approval_reference", "approved_by", "rationale"):
            if not str(item.get(field) or "").strip():
                raise IdentityMappingError(f"alias approval missing {field}: {stable_key}")
        group_key = (entity_type, stable_key)
        if group_key in approvals:
            raise IdentityMappingError(f"duplicate alias approval group: {stable_key}")
        for legacy_id in legacy_ids:
            legacy_key = (entity_type, legacy_id)
            if legacy_key in claimed_legacy:
                raise IdentityMappingError(f"legacy identity appears in multiple alias approvals: {legacy_id}")
            claimed_legacy.add(legacy_key)
        approvals[group_key] = {
            **item,
            "entity_type": entity_type,
            "stable_key": stable_key,
            "legacy_ids": legacy_ids,
            "approval_file_sha256": approval_file_sha256,
        }
    overrides: dict[tuple[str, str], dict[str, Any]] = {}
    for item in payload.get("identity_overrides") or []:
        entity_type = str(item.get("entity_type") or "").strip()
        legacy_id = str(item.get("legacy_id") or "").strip()
        ticker = _canonical_text(item.get("ticker")).upper()
        venue = _canonical_text(item.get("venue"))
        if entity_type != "company" or not legacy_id or not ticker or not venue:
            raise IdentityMappingError("identity override must identify company legacy id, ticker and venue")
        for field in ("approval_reference", "approved_by", "rationale"):
            if not str(item.get(field) or "").strip():
                raise IdentityMappingError(f"identity override missing {field}: company:{legacy_id}")
        key = (entity_type, legacy_id)
        if key in overrides:
            raise IdentityMappingError(f"duplicate identity override: {entity_type}:{legacy_id}")
        overrides[key] = {
            **item,
            "entity_type": entity_type,
            "legacy_id": legacy_id,
            "ticker": ticker,
            "venue": venue,
            "approval_file_sha256": approval_file_sha256,
        }
    return approvals, overrides


def _company_venue(row: dict[str, Any]) -> tuple[str | None, str | None]:
    ticker = _canonical_text(row.get("ticker")).upper()
    if "." in ticker:
        suffix = ticker.rsplit(".", 1)[1]
        venue = TICKER_SUFFIX_VENUES.get(suffix)
        if not venue:
            raise IdentityMappingError(f"unsupported ticker venue suffix: {ticker}")
        return venue, "ticker_exchange_suffix"
    market = _canonical_text(row.get("market"))
    if market in MARKET_VENUES:
        return MARKET_VENUES[market], "normalized_market"
    listing_status = _canonical_text(row.get("listing_status"))
    if listing_status in LISTING_STATUS_VENUES:
        return LISTING_STATUS_VENUES[listing_status], "normalized_listing_status"
    return None, None


def _approved_security_identity(approval: dict[str, Any]) -> tuple[str, str]:
    stable_key = str(approval.get("stable_key") or "").strip()
    match = SECURITY_STABLE_KEY_RE.fullmatch(stable_key)
    if match is None:
        raise IdentityMappingError(
            f"approved company alias is not a qualified security identity: {stable_key}"
        )
    ticker = _canonical_text(match.group("ticker")).upper()
    venue = _canonical_text(match.group("venue"))
    if not ticker or not venue:
        raise IdentityMappingError(f"approved company alias identity is incomplete: {stable_key}")
    return ticker, venue


def _table_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cursor = conn.execute(f'SELECT * FROM "{table}" ORDER BY 1')
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _table_schema(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [
        {
            "cid": row[0],
            "name": row[1],
            "type": row[2],
            "notnull": row[3],
            "default": row[4],
            "pk": row[5],
        }
        for row in conn.execute(f'PRAGMA table_info("{table}")')
    ]


def _industry_paths(rows: list[dict[str, Any]]) -> dict[str, str]:
    by_id = {str(row["id"]): row for row in rows}
    paths: dict[str, str] = {}

    def resolve(legacy_id: str, stack: tuple[str, ...] = ()) -> str:
        if legacy_id in paths:
            return paths[legacy_id]
        if legacy_id in stack:
            raise IdentityMappingError(f"industry parent cycle: {' -> '.join(stack + (legacy_id,))}")
        row = by_id.get(legacy_id)
        if row is None:
            raise IdentityMappingError(f"industry parent missing: {legacy_id}")
        name = _canonical_text(row.get("name"))
        if not name:
            raise IdentityMappingError(f"industry name empty: {legacy_id}")
        parent = row.get("parent_id")
        parent_path = ""
        if parent is not None:
            parent_path = resolve(str(parent), stack + (legacy_id,)) + "/"
        path = f"{parent_path}{name}"
        paths[legacy_id] = path
        return path

    for identity in by_id:
        resolve(identity)
    return paths


def _mapping_record(
    *,
    entity_type: str,
    source_table: str,
    legacy_id: str,
    stable_key: str,
    basis: str,
    row: dict[str, Any],
    source_watermark: dict[str, Any],
    identity_components: dict[str, Any] | None = None,
    alias_approval: dict[str, Any] | None = None,
    identity_override: dict[str, Any] | None = None,
    review_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "entity_type": entity_type,
        "source_database": "research.db",
        "source_table": source_table,
        "legacy_id": legacy_id,
        "stable_key": stable_key,
        "basis": basis,
        "source_watermark": source_watermark,
        "source_evidence_identity": _sha(
            {
                "entity_type": entity_type,
                "source_table": source_table,
                "legacy_id": legacy_id,
                "stable_key": stable_key,
                "row": row,
            }
        ),
    }
    if identity_components:
        record["identity_components"] = identity_components
    if alias_approval:
        record["alias_approval"] = {
            "approval_reference": alias_approval["approval_reference"],
            "approved_by": alias_approval["approved_by"],
            "rationale": alias_approval["rationale"],
            "approval_file_sha256": alias_approval["approval_file_sha256"],
        }
    if identity_override:
        record["identity_override"] = {
            "approval_reference": identity_override["approval_reference"],
            "approved_by": identity_override["approved_by"],
            "rationale": identity_override["rationale"],
            "approval_file_sha256": identity_override["approval_file_sha256"],
        }
    if review_identity:
        record["review_identity"] = review_identity
    return record


def build_identity_mapping(
    database: str | Path,
    *,
    alias_approvals: str | Path | None = None,
) -> dict[str, Any]:
    database_path = Path(database).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    database_file_sha256_before = _file_sha(database_path)
    conn = sqlite3.connect(
        f"file:{database_path.as_posix()}?mode=ro", uri=True, timeout=10
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = sorted(set(ENTITY_TABLES) - present)
        if missing:
            raise IdentityMappingError(f"missing identity tables: {', '.join(missing)}")
        rows = {table: _table_rows(conn, table) for table in ENTITY_TABLES}
        schemas = {table: _table_schema(conn, table) for table in ENTITY_TABLES}
        database_pragmas = {
            "application_id": int(conn.execute("PRAGMA application_id").fetchone()[0]),
            "schema_version": int(conn.execute("PRAGMA schema_version").fetchone()[0]),
            "user_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
        }
        conn.rollback()
    finally:
        conn.close()
    database_file_sha256_after = _file_sha(database_path)

    table_watermarks: dict[str, dict[str, Any]] = {}
    for table in ENTITY_TABLES:
        table_watermarks[table] = {
            "row_count": len(rows[table]),
            "schema_sha256": _sha(schemas[table]),
            "content_sha256": _sha(rows[table]),
        }

    mappings: list[dict[str, Any]] = []
    approvals, identity_overrides = _load_identity_approvals(alias_approvals)
    approval_by_legacy: dict[tuple[str, str], dict[str, Any]] = {}
    for approval in approvals.values():
        for legacy_id in approval["legacy_ids"]:
            approval_by_legacy[(approval["entity_type"], legacy_id)] = approval
    legacy_seen: dict[tuple[str, str], str] = {}
    stable_aliases: dict[tuple[str, str], list[str]] = {}
    used_identity_overrides: set[tuple[str, str]] = set()

    def add(record: dict[str, Any]) -> None:
        legacy_key = (record["entity_type"], record["legacy_id"])
        previous = legacy_seen.get(legacy_key)
        if previous is not None and previous != record["stable_key"]:
            raise IdentityMappingError(
                f"legacy identity maps to multiple stable keys for "
                f"{legacy_key[0]}:{legacy_key[1]}: {previous}, {record['stable_key']}"
            )
        legacy_seen[legacy_key] = record["stable_key"]
        stable_aliases.setdefault(
            (record["entity_type"], record["stable_key"]), []
        ).append(record["legacy_id"])
        mappings.append(record)

    for row in rows["company"]:
        legacy_id = str(row["id"])
        ticker = _canonical_text(row.get("ticker")).upper()
        market = _canonical_text(row.get("market"))
        name = _canonical_text(row.get("name"))
        alias_approval = approval_by_legacy.get(("company", legacy_id))
        identity_override = identity_overrides.get(("company", legacy_id))
        if alias_approval and identity_override:
            raise IdentityMappingError(
                f"company identity cannot use alias approval and venue override together: {legacy_id}"
            )
        if alias_approval:
            approved_ticker, approved_venue = _approved_security_identity(alias_approval)
            source_venue, source_venue_basis = _company_venue(row) if ticker else (None, None)
            if ticker and ticker != approved_ticker:
                raise IdentityMappingError(
                    f"approved alias ticker conflicts with source ticker for company:{legacy_id}"
                )
            if source_venue and source_venue != approved_venue:
                raise IdentityMappingError(
                    f"approved alias venue conflicts with source venue for company:{legacy_id}"
                )
            ticker = approved_ticker
            venue = approved_venue
            venue_basis = source_venue_basis or "approved_alias_security_identity"
            stable_key = alias_approval["stable_key"]
            basis = "approved_ticker_venue_alias"
        elif identity_override:
            if ticker and identity_override["ticker"] != ticker:
                raise IdentityMappingError(
                    f"identity override ticker mismatch for company:{legacy_id}"
                )
            ticker = identity_override["ticker"]
            venue = identity_override["venue"]
            venue_basis = "approved_identity_override"
            stable_key = f"company:security:{ticker}:venue:{venue}"
            basis = "normalized_ticker_and_approved_venue"
            used_identity_overrides.add(("company", legacy_id))
        elif ticker:
            venue, venue_basis = _company_venue(row)
            if not venue:
                raise IdentityMappingError(
                    f"ticker is not exchange-qualified and market is unavailable: company:{legacy_id}:{ticker}"
                )
            stable_key = f"company:security:{ticker}:venue:{venue}"
            basis = "normalized_ticker_and_venue"
        elif name:
            stable_key = f"company:name-market:{_sha([name, market])}"
            basis = "normalized_name_and_market_fallback"
            venue = None
            venue_basis = None
        else:
            raise IdentityMappingError(f"company identity empty: {legacy_id}")
        add(
            _mapping_record(
                entity_type="company",
                source_table="company",
                legacy_id=legacy_id,
                stable_key=stable_key,
                basis=basis,
                row=row,
                source_watermark=table_watermarks["company"],
                identity_components={
                    "ticker": ticker or None,
                    "venue": venue,
                    "venue_basis": venue_basis,
                    "market": market or None,
                },
                alias_approval=alias_approval,
                identity_override=identity_override,
                review_identity={
                    "display_name": str(row.get("name") or "").strip(),
                    "ticker": ticker or None,
                    "market": str(row.get("market") or "").strip() or None,
                },
            )
        )

    industry_paths = _industry_paths(rows["industry"])
    for row in rows["industry"]:
        legacy_id = str(row["id"])
        path = industry_paths[legacy_id]
        for entity_type in ("industry", "industry_q"):
            add(
                _mapping_record(
                    entity_type=entity_type,
                    source_table="industry",
                    legacy_id=legacy_id,
                    stable_key=f"{entity_type}:path:{path}",
                    basis="normalized_full_industry_path",
                    row=row,
                    source_watermark=table_watermarks["industry"],
                    review_identity={
                        "display_name": str(row.get("name") or "").strip(),
                        "parent_legacy_id": (
                            str(row.get("parent_id"))
                            if row.get("parent_id") is not None
                            else None
                        ),
                    },
                )
            )

    for row in rows["theme"]:
        legacy_id = str(row["id"])
        normalized_id = _canonical_text(legacy_id)
        if not normalized_id:
            raise IdentityMappingError("theme id is empty")
        add(
            _mapping_record(
                entity_type="theme",
                source_table="theme",
                legacy_id=legacy_id,
                stable_key=f"theme:id:{normalized_id}",
                basis="normalized_existing_text_primary_key",
                row=row,
                source_watermark=table_watermarks["theme"],
                review_identity={
                    "display_name": str(row.get("name") or "").strip(),
                },
            )
        )

    mappings.sort(key=lambda item: (item["entity_type"], item["legacy_id"]))
    alias_groups = []
    used_approvals: set[tuple[str, str]] = set()
    for (entity_type, stable_key), legacy_ids in sorted(stable_aliases.items()):
        if len(legacy_ids) <= 1:
            continue
        approval = approvals.get((entity_type, stable_key))
        normalized_ids = sorted(legacy_ids)
        if approval is None or approval["legacy_ids"] != normalized_ids:
            raise IdentityMappingError(
                f"stable identity collision is not an explicitly approved alias: {entity_type}:{stable_key}:{normalized_ids}"
            )
        used_approvals.add((entity_type, stable_key))
        alias_groups.append(
            {
                "entity_type": entity_type,
                "stable_key": stable_key,
                "legacy_ids": normalized_ids,
                "approval_reference": approval["approval_reference"],
                "approved_by": approval["approved_by"],
                "rationale": approval["rationale"],
                "approval_file_sha256": approval["approval_file_sha256"],
            }
        )
    unused = sorted(set(approvals) - used_approvals)
    if unused:
        raise IdentityMappingError(f"alias approvals do not match a current collision group: {unused}")
    unused_overrides = sorted(set(identity_overrides) - used_identity_overrides)
    if unused_overrides:
        raise IdentityMappingError(
            f"identity overrides were not required by current source data: {unused_overrides}"
        )
    snapshot_core = {
        "transaction_contract": {
            "mode": "explicit_read_transaction",
            "query_only": True,
            "tables_read_in_one_snapshot": list(ENTITY_TABLES),
        },
        "database_pragmas": database_pragmas,
        "source_tables": table_watermarks,
    }
    manifest_core = {
        "schema_version": "honghu.user_content_identity_mapping.v3",
        "source_database": str(database_path),
        "source_snapshot": {
            **snapshot_core,
            "snapshot_identity_sha256": _sha(snapshot_core),
            "database_file_diagnostics": {
                "role": "diagnostic_only_not_transaction_snapshot_identity",
                "sha256_before": database_file_sha256_before,
                "sha256_after": database_file_sha256_after,
                "stable_during_scan": (
                    database_file_sha256_before == database_file_sha256_after
                ),
            },
        },
        "source_tables": table_watermarks,
        "mappings": mappings,
        "collision_count": 0,
        "unapproved_alias_count": 0,
        "alias_approval_count": len(used_approvals),
        "identity_override_count": len(used_identity_overrides),
        "alias_group_count": len(alias_groups),
        "alias_groups": alias_groups,
    }
    return {
        **manifest_core,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": _sha(manifest_core),
    }


def write_identity_mapping(
    database: str | Path,
    output: str | Path,
    *,
    alias_approvals: str | Path | None = DEFAULT_ALIAS_APPROVALS,
) -> dict[str, Any]:
    manifest = build_identity_mapping(database, alias_approvals=alias_approvals)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only Stage 4 identity mapping")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--alias-approvals",
        type=Path,
        default=DEFAULT_ALIAS_APPROVALS,
    )
    args = parser.parse_args(argv)
    result = write_identity_mapping(
        args.database,
        args.output,
        alias_approvals=args.alias_approvals,
    )
    print(
        json.dumps(
            {
                "manifest_sha256": result["manifest_sha256"],
                "mapping_count": len(result["mappings"]),
                "snapshot_identity_sha256": result["source_snapshot"][
                    "snapshot_identity_sha256"
                ],
                "database_file_identity_role": result["source_snapshot"][
                    "database_file_diagnostics"
                ]["role"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
