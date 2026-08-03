from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from tools.opportunity_lens import build_byd_luxshare_optical_competition_run_pack as builder


class _PassingContractReport:
    valid = True
    warnings: list[object] = []

    def raise_for_errors(self) -> None:
        return None

    def as_dict(self) -> dict:
        return {"valid": True, "issues": [], "metrics": {}}


def test_byd_builder_writes_public_audit_and_fails_closed(tmp_path: Path):
    pack = {
        "pack_schema_version": "opportunity_lens.run_pack.v2",
        "workflow_contract_version": "research.workflow.v2",
        "slug": "byd-luxshare-bad-public-output",
        "display_title": "比亚迪与立讯风险报告",
        "research_question": "比亚迪与立讯是否进入光模块？",
        "problem_statement": "验证 builder 的公开内容门禁。",
        "build_metrics": {},
        "sections": [
            {
                "section_key": "bad",
                "section_title": "字段完成情况",
                "body_markdown": "canonical intake 与参数 owner 使用 D0/D1/D2。",
            }
        ],
        "entity_sections": [],
        "entities": [],
        "entity_investment_targets": [],
        "visuals": [],
        "nav": [],
        "supplement_requests": [],
    }
    pack_path = tmp_path / "run_pack.json"
    report_path = tmp_path / "final_report.md"
    validation_path = tmp_path / "validation_stage.json"
    summary_path = tmp_path / "build_summary.json"
    audit_json_path = tmp_path / "public_content_quality_audit.json"
    audit_md_path = tmp_path / "public_content_quality_audit.md"
    report_text = (
        "# 比亚迪与立讯风险报告\n\n"
        "## 字段完成情况\n\ncanonical intake 与参数 owner 使用 D0/D1/D2。\n"
    )
    with (
        mock.patch.object(builder, "build_pack", return_value=pack),
        mock.patch.object(builder, "validate_run_pack", return_value=_PassingContractReport()),
        mock.patch.object(builder, "_render_report", return_value=report_text),
        mock.patch.object(builder, "PACK_PATH", pack_path),
        mock.patch.object(builder, "REPORT_PATH", report_path),
        mock.patch.object(builder, "STAGE_VALIDATION_PATH", validation_path),
        mock.patch.object(builder, "BUILD_SUMMARY_PATH", summary_path),
        mock.patch.object(builder, "PUBLIC_CONTENT_AUDIT_JSON_PATH", audit_json_path),
        mock.patch.object(builder, "PUBLIC_CONTENT_AUDIT_MARKDOWN_PATH", audit_md_path),
        mock.patch.object(builder, "OUTPUT_DIR", tmp_path),
    ):
        with pytest.raises(ValueError, match="公开内容质量审计失败"):
            builder.write_pack()

    result = json.loads(audit_json_path.read_text(encoding="utf-8"))
    assert result["status"] == "FAIL"
    assert result["summary"]["errors"] > 0
    assert "结果：**FAIL**" in audit_md_path.read_text(encoding="utf-8")
    assert pack_path.is_file()
    assert report_path.is_file()
    assert not summary_path.exists()
