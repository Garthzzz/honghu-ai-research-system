from __future__ import annotations

"""Apply the frozen seven-row workbook seed to the PostgreSQL tracker."""

import argparse
import hashlib
import json
from pathlib import Path

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.financial.valuation_tracker import ValuationTrackerRepository, load_seed


REVIEWED_WORKBOOK_SEED_SHA256 = (
    "09907358d4e3ee9751e7196fcd9f27574553b434915bce38af3d7c4175f19e41"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-runtime-catalog", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    args = parser.parse_args(argv)
    if hashlib.sha256(args.seed.read_bytes()).hexdigest() != REVIEWED_WORKBOOK_SEED_SHA256:
        raise RuntimeError("workbook seed content hash is not reviewed")
    catalog = load_postgres_runtime_catalog(args.postgres_runtime_catalog)
    repo = ValuationTrackerRepository(
        build_catalog_connection_factory(catalog, role="reader"),
        build_catalog_connection_factory(catalog, role="writer_financial_data"),
    )
    seed = load_seed(args.seed)
    result = repo.seed_workbook(
        seed,
        actor=args.actor,
        idempotency_key=f"workbook-seed:{seed['workbook_sha256']}",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
