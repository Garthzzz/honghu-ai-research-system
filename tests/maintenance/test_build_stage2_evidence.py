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
        self.assertNotIn("tools/dynamic/secrets", text)


if __name__ == "__main__":
    unittest.main()
