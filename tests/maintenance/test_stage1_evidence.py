from __future__ import annotations

import json
from pathlib import Path

from tools.maintenance.build_stage1_evidence import ROOT, build_evidence, write_evidence


def test_stage1_evidence_binds_current_checkout_without_opening_ignored_files(tmp_path: Path) -> None:
    evidence = build_evidence(ROOT)

    assert len(evidence["binding"]["commit_sha"]) == 40
    assert evidence["tracked_inventory"]["file_count"] > 0
    assert len(evidence["capability_specs"]) == 7
    assert evidence["pending_review"]["record_count"] == 66
    assert evidence["pending_review"]["contains_raw_paths"] is False

    output = tmp_path / "evidence"
    write_evidence(evidence, output)
    inventory = json.loads((output / "final_inventory.json").read_text(encoding="utf-8"))
    identities = json.loads(
        (output / "capability_spec_identities.runtime.json").read_text(encoding="utf-8")
    )
    assert inventory["binding"]["commit_sha"] == evidence["binding"]["commit_sha"]
    assert identities["binding"] == evidence["binding"]
    assert (output / "stage1_completion_report.runtime.md").is_file()
