from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.research_core.config import resolve_track_config
from tools.research_core.manifest import hash_json
from tools.research_core.workflow import ResearchWorkflowRun


class ResearchWorkflowRunTests(unittest.TestCase):
    def test_persisted_run_composes_brief_gates_reviews_and_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "report.md"
            artifact.write_text("# 可验证研究报告\n", encoding="utf-8")
            run = ResearchWorkflowRun.start(
                run_dir=root / "run",
                run_key="demo-a",
                track="a",
                title="测试行业",
                research_question="测试行业的核心判断是什么？",
            )
            run.record_artifact("writing", artifact)
            for requirement in run.brief.requirements:
                run.record_requirement_coverage(
                    requirement.requirement_id,
                    "completed",
                    artifact_refs=[str(artifact)],
                )
            tasks = run.configure_reviews(artifacts={"public_markdown"})
            self.assertEqual([task.stage for task in tasks], ["evidence", "writing", "final"])
            for gate in resolve_track_config("a")["review"]["deterministic_gates"]:
                run.record_gate(gate, "GREEN", artifact_refs=[str(artifact)])
            for route in run.brief.modeling_routes:
                run.record_modeling_skill(
                    skill_name=route["skill_name"],
                    status="completed",
                    input_artifact=artifact,
                    output_artifact=artifact,
                )
            for stage in ("evidence", "writing", "final"):
                run.record_review(
                    stage=stage,
                    reviewer_role=f"{stage}_reviewer",
                    reviewer_id=f"independent-{stage}",
                    review_kind="independent",
                    verdict="GREEN",
                    reconciliation_status="resolved",
                    input_artifact=artifact,
                    output_artifact=artifact,
                )
            self.assertTrue(run.evaluate_publication())
            loaded = ResearchWorkflowRun.load(root / "run")
            self.assertEqual(loaded.brief.research_question, run.brief.research_question)
            self.assertEqual(loaded.manifest.publication["status"], "eligible")

    def test_requirement_coverage_blocks_publication_and_preserves_limitations(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = ResearchWorkflowRun.start(
                run_dir=Path(tmp) / "run",
                run_key="coverage-b",
                track="b",
                title="测试行业",
                research_question="核心判断是什么？",
                prompt_requirements=["必须回答客户验证"],
            )
            self.assertIn("unresolved_requirements:", " ".join(run.manifest.publication_blockers()))
            prompt_requirement = next(item for item in run.brief.requirements if item.origin == "prompt")
            with self.assertRaises(ValueError):
                run.record_requirement_coverage(prompt_requirement.requirement_id, "completed_with_limitation")
            run.record_requirement_coverage(
                prompt_requirement.requirement_id,
                "completed_with_limitation",
                note="客户未公开名称；已列出查证范围和替代验证指标。",
            )
            self.assertEqual(
                run.manifest.requirement_coverage[prompt_requirement.requirement_id].status,
                "completed_with_limitation",
            )

    def test_existing_run_dir_and_tampered_brief_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            ResearchWorkflowRun.start(
                run_dir=run_dir,
                run_key="once",
                track="a",
                title="测试行业",
                research_question="核心判断是什么？",
            )
            with self.assertRaises(FileExistsError):
                ResearchWorkflowRun.start(
                    run_dir=run_dir,
                    run_key="twice",
                    track="a",
                    title="测试行业",
                    research_question="核心判断是什么？",
                )
            brief_path = run_dir / "brief.json"
            payload = json.loads(brief_path.read_text(encoding="utf-8"))
            payload["research_question"] = "被篡改的问题"
            brief_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                ResearchWorkflowRun.load(run_dir)

    def test_c_track_keeps_mandatory_science_stage_even_when_artifact_list_is_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = ResearchWorkflowRun.start(
                run_dir=Path(tmp) / "run",
                run_key="demo-c",
                track="c",
                title="机会透镜测试",
                research_question="研究问题",
            )
            run.configure_reviews(artifacts={"public_markdown"})
            self.assertEqual(run.manifest.required_reviews, ["evidence", "science", "writing", "final"])

    def test_pre_versioned_brief_remains_loadable_without_losing_hash_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            ResearchWorkflowRun.start(
                run_dir=run_dir,
                run_key="legacy-brief",
                track="a",
                title="旧 brief 兼容",
                research_question="旧 brief 能否继续读取？",
            )
            path = run_dir / "brief.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.pop("brief_hash")
            payload.pop("brief_version")
            payload["brief_hash"] = hash_json(payload)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            loaded = ResearchWorkflowRun.load(run_dir)
            self.assertEqual(loaded.brief.research_question, "旧 brief 能否继续读取？")


if __name__ == "__main__":
    unittest.main()
