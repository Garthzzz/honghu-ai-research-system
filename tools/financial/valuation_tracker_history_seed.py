from __future__ import annotations

"""Seed the reviewed initial/current multi-method valuation history."""

import argparse
import hashlib
import json
from pathlib import Path

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.financial.valuation_tracker import ValuationTrackerRepository


REVIEWED_HISTORY_SHA256 = (
    "6210bc15f3884bb28e3c6bb9ea52d4dee2d5e68f5e33d90b771c7adcfea05ff0"
)
REVIEWED_PROMPT_SHA256 = (
    "c61fc6dac74db91446e7836bad4bce8794c77ddb86a0de162be2604a75abab5e"
)


def canonical_history_sha256(payload: dict) -> str:
    frozen = dict(payload)
    frozen.pop("artifact_sha256", None)
    encoded = json.dumps(
        frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_history(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "honghu.valuation_history.v2":
        raise RuntimeError("unsupported valuation history seed")
    observed = canonical_history_sha256(payload)
    if observed != REVIEWED_HISTORY_SHA256 or payload.get("artifact_sha256") != observed:
        raise RuntimeError("valuation history content hash is not reviewed")
    if payload.get("prompt_sha256") != REVIEWED_PROMPT_SHA256:
        raise RuntimeError("valuation history prompt contract is not reviewed")
    versions = payload.get("versions") or []
    if len(versions) != 11 or len({int(row["company_id"]) for row in versions}) != 7:
        raise RuntimeError("valuation history must contain 11 versions for seven companies")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-runtime-catalog", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    args = parser.parse_args(argv)
    payload = load_history(args.history)
    catalog = load_postgres_runtime_catalog(args.postgres_runtime_catalog)
    repo = ValuationTrackerRepository(
        build_catalog_connection_factory(catalog, role="reader"),
        build_catalog_connection_factory(catalog, role="writer_financial_data"),
    )
    members = {int(row["company_id"]): row for row in repo.watchlist()}
    if set(members) != {635, 634, 636, 650, 705, 706, 707}:
        raise RuntimeError("valuation history company set differs from the reviewed basket")
    resolved = []
    for source in payload["versions"]:
        member = members[int(source["company_id"])]
        if str(source["ticker"]).upper() != str(member["canonical_ticker"]).upper():
            raise RuntimeError("valuation history ticker differs from canonical identity")
        item = dict(source)
        item["security_id"] = int(member["security_id"])
        resolved.append(item)
    batch = dict(payload)
    batch["versions"] = resolved
    result = repo.seed_ai_history(
        batch,
        actor=args.actor,
        idempotency_key=f"valuation-history:{REVIEWED_HISTORY_SHA256}",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
