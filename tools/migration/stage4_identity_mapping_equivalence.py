from __future__ import annotations

"""Prove that an approved mapping and a safe SQLite snapshot are equivalent.

This verifier never grants or rewrites human approval.  It preserves the exact
approved manifest/snapshot identities and separately proves that a mapping
regenerated from a transactionally safe transfer snapshot has the same stable
business semantics.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from tools.migration.stage4_identity_mapping import (
    IdentityMappingResolver,
    _sha,
    mapping_semantic_core,
    mapping_semantic_identity,
    mapping_snapshot_identity,
)
from tools.migration.stage4_json_io import read_json


class IdentityMappingEquivalenceError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise IdentityMappingEquivalenceError(f"JSON object required: {path}")
    IdentityMappingResolver(value)
    return value


def compare_identity_mappings(
    approved: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    approved_core = mapping_semantic_core(approved)
    candidate_core = mapping_semantic_core(candidate)
    sections = sorted(
        name
        for name in approved_core
        if approved_core.get(name) != candidate_core.get(name)
    )
    core = {
        "schema_version": "honghu.identity_mapping_semantic_equivalence.v1",
        "status": "pass" if not sections else "fail",
        "approved_manifest_sha256": approved.get("manifest_sha256"),
        "approved_snapshot_identity_sha256": mapping_snapshot_identity(approved),
        "candidate_manifest_sha256": candidate.get("manifest_sha256"),
        "candidate_snapshot_identity_sha256": mapping_snapshot_identity(candidate),
        "approved_semantic_identity_sha256": mapping_semantic_identity(approved),
        "candidate_semantic_identity_sha256": mapping_semantic_identity(candidate),
        "semantic_equivalent": not sections,
        "differing_sections": sections,
        "excluded_physical_diagnostics": [
            "source_database_absolute_path",
            "source_snapshot.database_pragmas.schema_version",
            "source_snapshot.database_file_diagnostics",
            "generated_at",
        ],
        "approval_contract": {
            "approved_manifest_is_not_rewritten": True,
            "candidate_equivalence_does_not_grant_human_approval": True,
            "physical_diagnostics_are_not_authority_identity": True,
        },
    }
    return {**core, "evidence_sha256": _sha(core)}


def verify_files(
    *, approved_path: Path, candidate_path: Path, output_path: Path
) -> dict[str, Any]:
    result = compare_identity_mappings(_load(approved_path), _load(candidate_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = verify_files(
        approved_path=args.approved,
        candidate_path=args.candidate,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["semantic_equivalent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
