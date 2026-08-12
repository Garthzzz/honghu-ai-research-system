from __future__ import annotations

"""Run one allowlisted Stage 4 entrypoint from an exact checkout.

The bootstrap invokes this file with Python isolated mode.  Only the reviewed
repository root is added before importing an explicitly allowlisted module;
ambient PYTHONPATH and the working directory cannot select project code.
"""

import argparse
import importlib
import sys
from pathlib import Path


ALLOWED_MODULES = {
    "tools.migration.stage4_identity_mapping": "main",
    "tools.migration.stage4_identity_mapping_crosscheck": "main",
    "tools.migration.stage4_execution_bundle": "main",
    "tools.migration.stage4_execution_readiness": "main",
    "tools.migration.stage4_prepare_units": "main",
    "tools.migration.stage4_production_recovery": "main",
    "tools.migration.stage4_production_verify": "main",
    "tools.migration.stage4_repository_governance": "main",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--module", choices=sorted(ALLOWED_MODULES), required=True)
    args, remainder = parser.parse_known_args(argv)
    root = args.repo_root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise RuntimeError("reviewed repository root is missing AGENTS.md")
    sys.path.insert(0, str(root))
    module = importlib.import_module(args.module)
    entrypoint = getattr(module, ALLOWED_MODULES[args.module])
    return int(entrypoint(remainder))


if __name__ == "__main__":
    raise SystemExit(main())
