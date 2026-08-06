from __future__ import annotations

import unittest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools.maintenance.build_stage2_evidence import _github_binding


ROOT = Path(__file__).resolve().parents[2]


class Stage2EvidenceContractTests(unittest.TestCase):
    def test_stage2_evidence_builder_is_runtime_only_and_vm_honest(self):
        text = (ROOT / "tools/maintenance/build_stage2_evidence.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"validated_by_ci": False', text)
        self.assertIn('"database_hashes_unchanged": before == after', text)
        self.assertIn('"candidate_lifecycle": lifecycle', text)
        self.assertIn('"python_runtime": python_runtime', text)
        self.assertIn('python_runtime = verify_runtime(', text)
        self.assertIn('if not python_runtime["ok"]:', text)
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

    def test_pull_request_binding_distinguishes_merge_commit_from_head(self):
        with tempfile.TemporaryDirectory() as temp:
            event = Path(temp) / "event.json"
            event.write_text(
                json.dumps(
                    {
                        "pull_request": {
                            "head": {"sha": "A" * 40},
                            "base": {"sha": "B" * 40},
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "GITHUB_EVENT_NAME": "pull_request",
                    "GITHUB_EVENT_PATH": str(event),
                    "GITHUB_REF": "refs/pull/3/merge",
                },
                clear=False,
            ):
                binding = _github_binding("c" * 40, "3/merge")
        self.assertEqual(binding["commit_role"], "pull_request_merge")
        self.assertEqual(binding["pull_request_head_sha"], "a" * 40)
        self.assertEqual(binding["pull_request_base_sha"], "b" * 40)
        self.assertFalse(binding["eligible_as_vm_candidate_sha"])

    def test_push_binding_is_the_vm_candidate_commit_role(self):
        with patch.dict(
            os.environ,
            {"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/phase2/test"},
            clear=False,
        ):
            binding = _github_binding("d" * 40, "phase2/test")
        self.assertEqual(binding["commit_role"], "branch_commit")
        self.assertTrue(binding["eligible_as_vm_candidate_sha"])


if __name__ == "__main__":
    unittest.main()
