from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Stage2EvidenceContractTests(unittest.TestCase):
    def test_stage2_evidence_builder_is_runtime_only_and_vm_honest(self):
        text = (ROOT / "tools/maintenance/build_stage2_evidence.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"validated_by_ci": False', text)
        self.assertIn('"database_hashes_unchanged": before == after', text)
        self.assertIn('"candidate_lifecycle": lifecycle', text)
        self.assertIn('"port_released_after_stop": released', text)
        self.assertIn('"pid_matches_listener": pid_matches_listener', text)
        self.assertNotIn("tools/dynamic/secrets", text)

    def test_ci_invokes_stage2_evidence_as_a_package_module(self):
        workflow = (ROOT / ".github/workflows/stage1-ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "python -m tools.maintenance.build_stage2_evidence",
            workflow,
        )
        self.assertNotIn(
            "python tools/maintenance/build_stage2_evidence.py",
            workflow,
        )
        clean_job = workflow.split("  python-clean-environment:", 1)[1]
        self.assertIn(
            "python -m tools.maintenance.build_stage2_evidence",
            clean_job,
        )


if __name__ == "__main__":
    unittest.main()
