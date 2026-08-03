from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import (
    contract_version,
    load_workflow_config,
    manifest_contract_version,
    publish_review_stages,
    resolve_track_config,
)


SHA256_REF_RE = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def is_sha256_hash(value: Any) -> bool:
    return bool(SHA256_REF_RE.fullmatch(str(value or "")))


@dataclass
class GateResult:
    gate: str
    verdict: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=_now)


@dataclass
class ReviewRecord:
    stage: str
    reviewer_role: str
    verdict: str
    reconciliation_status: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    reviewer_id: str | None = None
    review_kind: str = "independent"
    input_artifact_hash: str | None = None
    output_artifact_hash: str | None = None
    input_artifact_ref: str | None = None
    output_artifact_ref: str | None = None
    reviewed_at: str = field(default_factory=_now)


@dataclass
class RequirementCoverage:
    requirement_id: str
    status: str = "pending"
    artifact_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    note: str | None = None
    updated_at: str = field(default_factory=_now)


@dataclass
class ExecutionManifest:
    run_key: str
    track: str
    request_ref: str | None = None
    manifest_version: str = field(default_factory=manifest_contract_version)
    workflow_contract_version: str = field(default_factory=contract_version)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    input_hashes: dict[str, str] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)
    gates: list[GateResult] = field(default_factory=list)
    reviews: list[ReviewRecord] = field(default_factory=list)
    required_reviews: list[str] = field(default_factory=list)
    requirement_coverage: dict[str, RequirementCoverage] = field(default_factory=dict)
    enforce_modeling_contract: bool = False
    modeling_requirements: list[dict[str, Any]] = field(default_factory=list)
    skill_invocations: list[dict[str, Any]] = field(default_factory=list)
    search_channel_records: list[dict[str, Any]] = field(default_factory=list)
    independent_model_freezes: list[dict[str, Any]] = field(default_factory=list)
    external_reconciliations: list[dict[str, Any]] = field(default_factory=list)
    publication: dict[str, Any] = field(default_factory=lambda: {"status": "staged", "blockers": []})

    def register_modeling_requirements(self, routes: list[dict[str, Any]]) -> None:
        self.modeling_requirements = [dict(route) for route in routes]
        self.record_stage(
            "model_routing",
            "completed",
            required_skills=[route.get("skill_name") for route in routes],
        )

    def record_skill_invocation(
        self,
        *,
        skill_name: str,
        status: str,
        input_artifact_hash: str | None = None,
        output_artifact_hash: str | None = None,
        note: str | None = None,
    ) -> None:
        required = {str(item.get("skill_name")) for item in self.modeling_requirements}
        if skill_name not in required:
            raise ValueError(f"未由研究路由触发的 Skill 不得登记为强制执行：{skill_name}")
        if status not in {"loaded", "completed", "blocked", "not_applicable"}:
            raise ValueError(f"非法 Skill 执行状态：{status}")
        if status == "completed" and (not input_artifact_hash or not output_artifact_hash):
            raise ValueError("完成的 Skill 调用必须绑定输入和输出 SHA256")
        for value in (input_artifact_hash, output_artifact_hash):
            if value and not is_sha256_hash(value):
                raise ValueError("Skill artifact hash 必须是 sha256:<64位十六进制>")
        self.skill_invocations.append({
            "skill_name": skill_name,
            "status": status,
            "input_artifact_hash": input_artifact_hash,
            "output_artifact_hash": output_artifact_hash,
            "note": str(note or "").strip() or None,
            "recorded_at": _now(),
        })
        self.updated_at = _now()

    def record_search_channel(
        self,
        *,
        task_id: str,
        source_channel: str,
        status: str,
        result_count: int,
        gap_trigger: str | None = None,
    ) -> None:
        if source_channel not in {"report", "web"}:
            raise ValueError(f"非法 source_channel: {source_channel}")
        if status not in {"planned", "completed", "blocked"}:
            raise ValueError(f"非法搜索状态: {status}")
        if str(task_id).startswith("search.r2") and not str(gap_trigger or "").strip():
            raise ValueError("第二轮搜索必须记录 gap_trigger")
        self.search_channel_records.append({
            "task_id": task_id,
            "source_channel": source_channel,
            "status": status,
            "result_count": max(0, int(result_count)),
            "gap_trigger": str(gap_trigger or "").strip() or None,
            "recorded_at": _now(),
        })
        self.updated_at = _now()

    def record_independent_freeze(self, *, model_ref: str, input_hash: str, output_hash: str, frozen_before_consensus: bool) -> None:
        if not is_sha256_hash(input_hash) or not is_sha256_hash(output_hash):
            raise ValueError("独立模型冻结必须绑定有效 SHA256")
        if not frozen_before_consensus:
            raise ValueError("公司独立预测必须在读取一致预期前冻结")
        self.independent_model_freezes.append({
            "model_ref": model_ref,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "frozen_before_consensus": True,
            "frozen_at": _now(),
        })
        self.updated_at = _now()

    def record_external_reconciliation(self, *, model_ref: str, benchmark_ref: str, artifact_hash: str, status: str) -> None:
        if status not in {"completed", "completed_with_gap", "blocked"}:
            raise ValueError(f"非法外部对账状态: {status}")
        if not is_sha256_hash(artifact_hash):
            raise ValueError("外部对账必须绑定有效 SHA256")
        self.external_reconciliations.append({
            "model_ref": model_ref,
            "benchmark_ref": benchmark_ref,
            "artifact_hash": artifact_hash,
            "status": status,
            "recorded_at": _now(),
        })
        self.updated_at = _now()

    def record_stage(self, name: str, status: str, **metadata: Any) -> None:
        self.stages.append({"name": name, "status": status, "recorded_at": _now(), **metadata})
        self.updated_at = _now()

    def record_gate(self, result: GateResult) -> None:
        if result.verdict not in {"GREEN", "YELLOW", "RED"}:
            raise ValueError(f"非法 gate verdict: {result.verdict}")
        canonical = set(resolve_track_config(self.track).get("review", {}).get("deterministic_gates", []))
        if result.gate not in canonical:
            raise ValueError(f"非法 deterministic gate: {result.gate}")
        self.gates.append(result)
        self.updated_at = _now()

    def record_review(self, record: ReviewRecord) -> None:
        if record.verdict not in {"GREEN", "YELLOW", "RED"}:
            raise ValueError(f"非法 review verdict: {record.verdict}")
        canonical = set(resolve_track_config(self.track).get("review", {}).get("canonical_review_stages", []))
        if record.stage not in canonical:
            raise ValueError(f"非法 review stage: {record.stage}")
        if record.review_kind not in {"independent", "human", "deterministic"}:
            raise ValueError(f"非法 review kind: {record.review_kind}")
        if record.reconciliation_status not in {"pending", "resolved", "deferred_to_user", "blocked", "not_applicable"}:
            raise ValueError(f"非法 reconciliation_status: {record.reconciliation_status}")
        if not record.input_artifact_hash or not record.output_artifact_hash:
            raise ValueError("review record 必须同时记录 input_artifact_hash 和 output_artifact_hash")
        if not is_sha256_hash(record.input_artifact_hash) or not is_sha256_hash(record.output_artifact_hash):
            raise ValueError("review artifact hash 必须是 sha256:<64位十六进制>")
        if record.review_kind in {"independent", "human"} and not record.reviewer_id:
            raise ValueError("independent/human review 必须记录 reviewer_id")
        self.reviews.append(record)
        self.updated_at = _now()

    def set_review_plan(self, stages: list[str]) -> None:
        canonical_order = resolve_track_config(self.track).get("review", {}).get("canonical_review_stages", [])
        canonical = set(canonical_order)
        selected = set(str(stage).strip() for stage in stages if str(stage).strip())
        unknown = sorted(selected - canonical)
        if unknown:
            raise ValueError(f"review plan 含未知 stage: {unknown}")
        selected.add("final")
        self.required_reviews = [stage for stage in canonical_order if stage in selected]
        self.updated_at = _now()

    def record_requirement_coverage(
        self,
        requirement_id: str,
        status: str,
        *,
        artifact_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        note: str | None = None,
    ) -> None:
        if requirement_id not in self.requirement_coverage:
            raise ValueError(f"未知 requirement_id: {requirement_id}")
        allowed = {"pending", "completed", "completed_with_limitation", "blocked"}
        if status not in allowed:
            raise ValueError(f"非法 requirement coverage status: {status}")
        clean_note = str(note or "").strip() or None
        if status in {"completed_with_limitation", "blocked"} and not clean_note:
            raise ValueError(f"{status} 必须说明限制或阻塞原因")
        self.requirement_coverage[requirement_id] = RequirementCoverage(
            requirement_id=requirement_id,
            status=status,
            artifact_refs=list(dict.fromkeys(artifact_refs or [])),
            evidence_refs=list(dict.fromkeys(evidence_refs or [])),
            note=clean_note,
        )
        self.updated_at = _now()

    def publication_blockers(self, *, open_p0: int = 0) -> list[str]:
        blockers: list[str] = []
        profile = resolve_track_config(self.track)
        latest_gates: dict[str, GateResult] = {}
        for result in self.gates:
            latest_gates[result.gate] = result
        required_gates = profile.get("review", {}).get("deterministic_gates", [])
        missing_gates = [gate for gate in required_gates if gate not in latest_gates]
        if missing_gates:
            blockers.append("missing_deterministic_gates:" + ",".join(missing_gates))
        if any(g.verdict == "RED" for g in latest_gates.values()):
            blockers.append("deterministic_gate_red")
        latest_reviews: dict[str, ReviewRecord] = {}
        for record in self.reviews:
            latest_reviews[record.stage] = record
        required_reviews = self.required_reviews or list(profile.get("publish_requires_review_records", []))
        if "final" not in required_reviews:
            required_reviews.append("final")
        for stage in required_reviews:
            record = latest_reviews.get(stage)
            if record is None:
                blockers.append(f"missing_required_review:{stage}")
                continue
            if record.verdict != "GREEN" or record.reconciliation_status not in {"resolved", "not_applicable"}:
                blockers.append(f"review_not_green_or_unresolved:{stage}")
            if not record.input_artifact_hash:
                blockers.append(f"review_missing_input_hash:{stage}")
            elif not is_sha256_hash(record.input_artifact_hash):
                blockers.append(f"review_invalid_input_hash:{stage}")
            if not record.output_artifact_hash:
                blockers.append(f"review_missing_output_hash:{stage}")
            elif not is_sha256_hash(record.output_artifact_hash):
                blockers.append(f"review_invalid_output_hash:{stage}")
        final = latest_reviews.get("final")
        if final and final.review_kind not in {"independent", "human"}:
            blockers.append("final_review_not_independent")
        if open_p0:
            blockers.append("open_p0")
        unresolved_requirements = sorted(
            requirement_id
            for requirement_id, coverage in self.requirement_coverage.items()
            if coverage.status in {"pending", "blocked"}
        )
        if unresolved_requirements:
            blockers.append("unresolved_requirements:" + ",".join(unresolved_requirements))
        if self.enforce_modeling_contract:
            latest_skills: dict[str, dict[str, Any]] = {}
            for invocation in self.skill_invocations:
                latest_skills[str(invocation.get("skill_name"))] = invocation
            for route in self.modeling_requirements:
                skill_name = str(route.get("skill_name") or "")
                if skill_name and latest_skills.get(skill_name, {}).get("status") != "completed":
                    blockers.append(f"required_modeling_skill_not_completed:{skill_name}")
            required_names = {str(item.get("skill_name")) for item in self.modeling_requirements}
            if "company_financial_modeling" in required_names and not self.independent_model_freezes:
                blockers.append("missing_independent_financial_model_freeze")
            if required_names & {"company_financial_modeling", "company_valuation_modeling"} and not self.external_reconciliations:
                blockers.append("missing_external_reconciliation")
        return blockers

    def evaluate_publication(self, *, open_p0: int = 0) -> bool:
        blockers = self.publication_blockers(open_p0=open_p0)
        self.publication = {
            "status": "eligible" if not blockers else "blocked",
            "blockers": blockers,
            "evaluated_at": _now(),
        }
        self.updated_at = _now()
        return not blockers

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["manifest_hash"] = hash_json({k: v for k, v in payload.items() if k != "manifest_hash"})
        return payload

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + f".{uuid4().hex}.tmp")
        try:
            tmp.write_text(json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
        return target

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutionManifest":
        data = dict(payload)
        expected_hash = data.pop("manifest_hash", None)
        if not expected_hash:
            raise ValueError("execution manifest 缺少 manifest_hash")
        if expected_hash != hash_json(data):
            raise ValueError("execution manifest hash 校验失败，文件可能被修改或损坏")
        data["gates"] = [item if isinstance(item, GateResult) else GateResult(**item) for item in data.get("gates", [])]
        data["reviews"] = [item if isinstance(item, ReviewRecord) else ReviewRecord(**item) for item in data.get("reviews", [])]
        data["requirement_coverage"] = {
            key: item if isinstance(item, RequirementCoverage) else RequirementCoverage(**item)
            for key, item in data.get("requirement_coverage", {}).items()
        }
        for key, item in data["requirement_coverage"].items():
            if key != item.requirement_id:
                raise ValueError(f"requirement coverage key 与 requirement_id 不一致: {key}")
        manifest = cls(**data)
        config = load_workflow_config()
        if manifest.manifest_version != config["manifest_version"]:
            raise ValueError(f"不支持的 manifest_version: {manifest.manifest_version}")
        if manifest.workflow_contract_version != config["contract_version"]:
            raise ValueError(f"不支持的 workflow_contract_version: {manifest.workflow_contract_version}")
        resolve_track_config(manifest.track)
        if not str(manifest.run_key or "").strip():
            raise ValueError("execution manifest run_key 不能为空")
        return manifest

    @classmethod
    def read(cls, path: str | Path) -> "ExecutionManifest":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def required_review_stages(track: str) -> list[str]:
    return publish_review_stages(track)
