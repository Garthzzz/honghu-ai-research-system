from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import RESEARCH_WORKFLOW_CONTRACT_VERSION, RUN_PACK_SCHEMA_VERSION
from .run_pack_contract import validate_run_pack


@dataclass
class RunPackBuilder:
    """Canonical V2 builder; topic-specific research supplies content, not schema glue."""

    slug: str
    research_question: str
    intake: dict[str, Any]
    display_title: str | None = None
    requested_by: str = "research_workflow_v2"
    run_mode: str = "c_hybrid"
    quality_profile: str = "standard"
    problem_statement: str | None = None
    public_section_structure_contract: str | None = None
    homepage_section_min_characters: int | None = None
    homepage_section_max_characters: int | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    data_points: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    entity_sections: list[dict[str, Any]] = field(default_factory=list)
    entity_investment_targets: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    visuals: list[dict[str, Any]] = field(default_factory=list)
    early_signals: list[dict[str, Any]] = field(default_factory=list)
    supplement_requests: list[dict[str, Any]] = field(default_factory=list)
    audit_issues: list[dict[str, Any]] = field(default_factory=list)
    review_records: list[dict[str, Any]] = field(default_factory=list)
    search_plan: list[dict[str, Any]] = field(default_factory=list)
    modeling_records: list[dict[str, Any]] = field(default_factory=list)
    independent_model_freezes: list[dict[str, Any]] = field(default_factory=list)
    external_reconciliations: list[dict[str, Any]] = field(default_factory=list)
    evidence_groups: dict[str, str] = field(default_factory=dict)

    def add_source(self, source: dict[str, Any]) -> None:
        required = {
            "ref", "title", "publisher", "source_tier", "source_review_status",
            "excerpt", "language", "independence_key", "independence_rationale", "source_channel",
        }
        missing = sorted(key for key in required if not source.get(key))
        if not source.get("url") and not source.get("local_path"):
            missing.append("url_or_local_path")
        if str(source.get("language") or "").lower().startswith("en"):
            missing.extend(key for key in ("title_zh", "excerpt_zh") if not source.get(key))
        if missing:
            raise ValueError(f"V2 source 缺少字段: {sorted(set(missing))}")
        if source.get("source_channel") not in {"report", "web"}:
            raise ValueError("V2 source_channel 必须是 report 或 web")
        self.sources.append(dict(source))

    def add_paper_manifest_source(
        self,
        entry: dict[str, Any],
        *,
        project_root: str | Path,
        ref: str,
        excerpt: str,
        excerpt_zh: str | None = None,
        title_zh: str | None = None,
    ) -> None:
        """经文件哈希和译意门禁把下载研报加入 C 轨 source producer。"""

        from tools.pipeline.paper_source_manifest import opportunity_source_from_manifest

        self.add_source(
            opportunity_source_from_manifest(
                entry,
                project_root=Path(project_root),
                ref=ref,
                excerpt=excerpt,
                excerpt_zh=excerpt_zh,
                title_zh=title_zh,
            )
        )

    def add_entity(self, entity: dict[str, Any]) -> None:
        if entity.get("entity_research_mode") not in {"market_linked", "theory_research"}:
            raise ValueError("V2 entity 必须显式声明 entity_research_mode")
        self.entities.append(dict(entity))

    def add_review_record(self, record: dict[str, Any]) -> None:
        required = {
            "stage", "reviewer_role", "reviewer_id", "review_kind", "verdict",
            "reconciliation_status", "input_artifact_hash", "output_artifact_hash", "findings",
        }
        missing = sorted(key for key in required if not record.get(key))
        if "findings" in record and not isinstance(record["findings"], list):
            raise ValueError("review record findings 必须是数组")
        if record.get("findings") == []:
            missing = [key for key in missing if key != "findings"]
        if missing:
            raise ValueError(f"review record 缺少字段: {missing}")
        self.review_records.append(dict(record))

    def build(self, *, publication_mode: str = "stage") -> dict[str, Any]:
        pack = {
            "pack_schema_version": RUN_PACK_SCHEMA_VERSION,
            "workflow_contract_version": RESEARCH_WORKFLOW_CONTRACT_VERSION,
            "search_channel_contract_version": "research.search_channels.v1",
            "modeling_contract_version": "research.modeling_skills.v1",
            "quality_profile": self.quality_profile,
            "slug": self.slug,
            "display_title": self.display_title or self.problem_statement or self.research_question,
            "research_question": self.research_question,
            "problem_statement": self.problem_statement or self.research_question,
            "requested_by": self.requested_by,
            "run_mode": self.run_mode,
            "intake": self.intake,
            "search_plan": self.search_plan,
            "modeling_records": self.modeling_records,
            "independent_model_freezes": self.independent_model_freezes,
            "external_reconciliations": self.external_reconciliations,
            "sources": self.sources,
            "evidence_groups": self.evidence_groups,
            "claims": self.claims,
            "data_points": self.data_points,
            "entities": self.entities,
            "entity_sections": self.entity_sections,
            "entity_investment_targets": self.entity_investment_targets,
            "sections": self.sections,
            "visuals": self.visuals,
            "early_signals": self.early_signals,
            "supplement_requests": self.supplement_requests,
            "audit_issues": self.audit_issues,
            "review_records": self.review_records,
        }
        if self.public_section_structure_contract:
            pack["public_section_structure_contract"] = (
                self.public_section_structure_contract
            )
        if self.homepage_section_min_characters is not None:
            pack["homepage_section_min_characters"] = int(
                self.homepage_section_min_characters
            )
        if self.homepage_section_max_characters is not None:
            pack["homepage_section_max_characters"] = int(
                self.homepage_section_max_characters
            )
        report = validate_run_pack(pack, publication_mode=publication_mode)
        report.raise_for_errors()
        return pack
