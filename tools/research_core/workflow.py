from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .brief import ResearchBrief, Requirement, compile_research_brief
from .config import resolve_track_config
from .manifest import ExecutionManifest, GateResult, RequirementCoverage, ReviewRecord, hash_file
from .quality import ReviewTask, build_review_plan


class ResearchWorkflowRun:
    """Persisted A/B/C workflow state without embedding topic-specific research prompts."""

    def __init__(self, run_dir: str | Path, brief: ResearchBrief, manifest: ExecutionManifest):
        self.run_dir = Path(run_dir)
        self.brief = brief
        self.manifest = manifest

    @property
    def brief_path(self) -> Path:
        return self.run_dir / "brief.json"

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def start(
        cls,
        *,
        run_dir: str | Path,
        run_key: str,
        track: str,
        title: str,
        research_question: str,
        request_ref: str | Path | None = None,
        prompt_requirements: Iterable[str | dict[str, Any]] = (),
        replace_existing: bool = False,
        **brief_fields: Any,
    ) -> "ResearchWorkflowRun":
        root = Path(run_dir)
        if not str(run_key or "").strip():
            raise ValueError("run_key 不能为空")
        existing = [path for path in (root / "brief.json", root / "manifest.json") if path.exists()]
        if existing and not replace_existing:
            raise FileExistsError(f"run_dir 已包含执行记录，请使用 load() 恢复而不是覆盖: {root}")
        if existing:
            archive_dir = root / "history" / uuid4().hex
            archive_dir.mkdir(parents=True, exist_ok=False)
            for path in existing:
                shutil.copy2(path, archive_dir / path.name)
        brief = compile_research_brief(
            track=track,
            title=title,
            research_question=research_question,
            prompt_requirements=prompt_requirements,
            **brief_fields,
        )
        manifest = ExecutionManifest(
            run_key=run_key,
            track=brief.track,
            request_ref=str(request_ref) if request_ref else None,
            enforce_modeling_contract=True,
            requirement_coverage={
                item.requirement_id: RequirementCoverage(item.requirement_id)
                for item in brief.requirements
            },
        )
        manifest.register_modeling_requirements(brief.modeling_routes)
        for task in brief.search_plan.get("tasks", []):
            manifest.record_search_channel(
                task_id=str(task["task_id"]),
                source_channel=str(task["source_channel"]),
                status="planned",
                result_count=0,
                gap_trigger=task.get("gap_trigger"),
            )
        if request_ref and Path(request_ref).is_file():
            manifest.input_hashes[str(Path(request_ref))] = hash_file(request_ref)
        manifest.record_stage("intake", "completed", brief_hash=brief.as_dict()["brief_hash"])
        run = cls(run_dir, brief, manifest)
        run._persist()
        return run

    @classmethod
    def load(cls, run_dir: str | Path) -> "ResearchWorkflowRun":
        root = Path(run_dir)
        brief_payload = json.loads((root / "brief.json").read_text(encoding="utf-8"))
        expected_brief_hash = brief_payload.pop("brief_hash", None)
        if not expected_brief_hash:
            raise ValueError("research brief 缺少 brief_hash")
        legacy_without_version = "brief_version" not in brief_payload
        canonical = json.dumps(brief_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stored_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if expected_brief_hash != stored_hash:
            raise ValueError("research brief hash 校验失败，文件可能被修改或损坏")
        brief_payload["requirements"] = [Requirement(**item) for item in brief_payload.get("requirements", [])]
        brief = ResearchBrief(**brief_payload)
        manifest = ExecutionManifest.read(root / "manifest.json")
        if brief.track != manifest.track:
            raise ValueError("brief.track 与 manifest.track 不一致")
        if brief.workflow_contract_version != manifest.workflow_contract_version:
            raise ValueError("brief 与 manifest 的 workflow contract 版本不一致")
        return cls(root, brief, manifest)

    def _persist(self) -> None:
        self._atomic_json(self.brief_path, self.brief.as_dict())
        self.manifest.write(self.manifest_path)

    def record_artifact(self, stage: str, path: str | Path, *, status: str = "completed", **metadata: Any) -> str:
        artifact = Path(path)
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        digest = hash_file(artifact)
        self.manifest.record_stage(
            stage,
            status,
            artifact_path=str(artifact),
            artifact_hash=digest,
            **metadata,
        )
        self._persist()
        return digest

    def record_stage(self, stage: str, status: str, **metadata: Any) -> None:
        self.manifest.record_stage(stage, status, **metadata)
        self._persist()

    def record_input_artifacts(self, paths: Iterable[str | Path]) -> dict[str, str]:
        recorded: dict[str, str] = {}
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file():
                raise FileNotFoundError(path)
            recorded[str(path)] = hash_file(path)
        self.manifest.input_hashes.update(recorded)
        self._persist()
        return recorded

    def configure_reviews(self, *, artifacts: Iterable[str], risks: Iterable[str] = ()) -> list[ReviewTask]:
        tasks = build_review_plan(track=self.brief.track, artifacts=artifacts, risks=risks)
        stages = [task.stage for task in tasks]
        mandatory = resolve_track_config(self.brief.track).get("publish_requires_review_records", [])
        self.manifest.set_review_plan(list(dict.fromkeys([*mandatory, *stages])))
        self._persist()
        return tasks

    def record_gate(self, gate: str, verdict: str, findings: list[dict[str, Any]] | None = None, artifact_refs: list[str] | None = None) -> None:
        self.manifest.record_gate(GateResult(gate, verdict, findings or [], artifact_refs or []))
        self._persist()

    def record_review(
        self,
        *,
        stage: str,
        reviewer_role: str,
        reviewer_id: str,
        review_kind: str,
        verdict: str,
        reconciliation_status: str,
        input_artifact: str | Path,
        output_artifact: str | Path,
        findings: list[dict[str, Any]] | None = None,
    ) -> None:
        self.manifest.record_review(
            ReviewRecord(
                stage=stage,
                reviewer_role=reviewer_role,
                reviewer_id=reviewer_id,
                review_kind=review_kind,
                verdict=verdict,
                reconciliation_status=reconciliation_status,
                findings=findings or [],
                input_artifact_hash=hash_file(input_artifact),
                output_artifact_hash=hash_file(output_artifact),
                input_artifact_ref=str(input_artifact),
                output_artifact_ref=str(output_artifact),
            )
        )
        self._persist()

    def record_requirement_coverage(
        self,
        requirement_id: str,
        status: str,
        *,
        artifact_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        note: str | None = None,
    ) -> None:
        self.manifest.record_requirement_coverage(
            requirement_id,
            status,
            artifact_refs=artifact_refs,
            evidence_refs=evidence_refs,
            note=note,
        )
        self._persist()

    def record_modeling_skill(
        self,
        *,
        skill_name: str,
        status: str,
        input_artifact: str | Path | None = None,
        output_artifact: str | Path | None = None,
        note: str | None = None,
    ) -> None:
        self.manifest.record_skill_invocation(
            skill_name=skill_name,
            status=status,
            input_artifact_hash=hash_file(input_artifact) if input_artifact else None,
            output_artifact_hash=hash_file(output_artifact) if output_artifact else None,
            note=note,
        )
        self._persist()

    def record_independent_model_freeze(
        self,
        *,
        model_ref: str,
        input_artifact: str | Path,
        output_artifact: str | Path,
    ) -> None:
        self.manifest.record_independent_freeze(
            model_ref=model_ref,
            input_hash=hash_file(input_artifact),
            output_hash=hash_file(output_artifact),
            frozen_before_consensus=True,
        )
        self._persist()

    def record_external_reconciliation(
        self,
        *,
        model_ref: str,
        benchmark_ref: str,
        artifact: str | Path,
        status: str = "completed",
    ) -> None:
        self.manifest.record_external_reconciliation(
            model_ref=model_ref,
            benchmark_ref=benchmark_ref,
            artifact_hash=hash_file(artifact),
            status=status,
        )
        self._persist()

    def evaluate_publication(self, *, open_p0: int = 0) -> bool:
        eligible = self.manifest.evaluate_publication(open_p0=open_p0)
        self._persist()
        return eligible


def start_from_request_file(request_path: str | Path, run_dir: str | Path) -> ResearchWorkflowRun:
    payload = json.loads(Path(request_path).read_text(encoding="utf-8"))
    allowed = {
        "run_key", "track", "title", "research_question", "prompt_requirements",
        "decision_use", "must_include", "exclusions", "special_constraints",
        "scope", "time_window", "required_artifacts", "quality_floor",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"workflow request 含未知字段: {unknown}")
    return ResearchWorkflowRun.start(
        run_dir=run_dir,
        request_ref=request_path,
        **payload,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 A/B/C V2 ResearchBrief 与 execution manifest")
    parser.add_argument("request", type=Path, help="结构化 workflow request JSON")
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run = start_from_request_file(args.request, args.run_dir)
    print(json.dumps({
        "brief": str(run.brief_path),
        "manifest": str(run.manifest_path),
        "workflow_contract_version": run.manifest.workflow_contract_version,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
