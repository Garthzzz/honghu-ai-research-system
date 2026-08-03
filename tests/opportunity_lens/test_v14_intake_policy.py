from __future__ import annotations

import unittest
from pathlib import Path

from tools.opportunity_lens.intake_parser import parse_intake_payload, parse_markdown_intake_text
from tools.opportunity_lens.search_models import build_policy_search_profile
from tools.opportunity_lens.validators import ValidationError
from tools.opportunity_lens.verification_gate import evaluate_policy_gate


class V14IntakePolicyTests(unittest.TestCase):
    def test_public_parser_rejects_available_materials_state(self):
        with self.assertRaises(ValidationError):
            parse_intake_payload({"research_question": "测试", "available_materials_state": "B"})

    def test_public_parser_requires_explicit_material_choice(self):
        with self.assertRaises(ValueError):
            parse_intake_payload({"research_question": "测试"})

    def test_legacy_parser_normalizes_available_materials_state(self):
        parsed = parse_intake_payload(
            {"research_question": "测试", "available_materials_state": "B", "papers_or_report_folder": "papers/demo"},
            allow_legacy_alias=True,
        )
        self.assertEqual(parsed["available_materials_choice"], "B")
        self.assertEqual(parsed["intake_material_type"], "papers_folder")
        self.assertNotIn("available_materials_state", parsed)

    def test_policy_search_profile_is_local_and_versionable(self):
        profile = build_policy_search_profile("freshness_first")
        self.assertEqual(profile["evidence_policy"], "freshness_first")
        self.assertEqual(profile["real_search_executor"], "deferred")
        self.assertIn("official_recent", profile["source_groups"])

    def test_gate_routes_gray_freshness_evidence_to_early_signal_only(self):
        result = evaluate_policy_gate(
            evidence_policy="freshness_first",
            source_tier="D",
            source_review_status="weak_source_only",
            official_confirmation_status="rumor_unconfirmed",
        )
        self.assertEqual(result.policy_gate_verdict, "pass_early_signal")
        self.assertEqual(result.scoring_eligibility, "early_signal_only")

    def test_all_current_formal_requests_parse_without_contract_issues(self):
        root = Path(__file__).resolve().parents[2]
        request_dir = root / "opportunity_lens" / "intake_requests"
        request_paths = sorted(path for path in request_dir.glob("*.md") if path.name != "README.md")
        self.assertGreaterEqual(len(request_paths), 1)
        for path in request_paths:
            with self.subTest(path=path.name):
                parsed = parse_markdown_intake_text(path.read_text(encoding="utf-8"))
                self.assertTrue(parsed["research_question"].strip())
                self.assertIn(parsed["available_materials_choice"], {"A", "B", "C"})
                self.assertIn(parsed["evidence_policy"], {"freshness_first", "balanced", "accuracy_first"})
                self.assertEqual(parsed["validation_issues"], [])

    def test_material_choice_b_accepts_professional_delivery_note_without_local_path(self):
        parsed = parse_intake_payload(
            {
                "research_question": "研究资料包中的产业问题",
                "available_materials_choice": "B",
                "materials_delivery_note": "研报资料包已发送给研究负责人，并已通过企业微信完成交付通知。",
            }
        )
        self.assertEqual(parsed["intake_material_type"], "papers_folder")
        self.assertEqual(parsed["validation_issues"], [])

    def test_markdown_material_path_keeps_supplementary_evidence_constraints(self):
        parsed = parse_markdown_intake_text(
            """# 正式研究请求

## 必填 1：研究问题
```text
核验新进入者是否形成规模竞争。
```

## 必填 2：可用资料状态
选择（A / B / C）：
```text
B
```
资料路径 / 行研库行业名称：
```text
D:\\quant\\industry_demo\\papers\\demo
```
补充说明：
```text
本地研报仅作线索，所有关键结论必须回到独立一手来源核验。
```

## 必填 3：证据策略
选择（A / B / C）：
```text
A
```
"""
        )
        self.assertEqual(
            parsed["papers_or_report_folder"],
            "D:\\quant\\industry_demo\\papers\\demo",
        )
        self.assertEqual(
            parsed["materials_delivery_note"],
            "本地研报仅作线索，所有关键结论必须回到独立一手来源核验。",
        )

    def test_material_choice_and_material_type_cannot_contradict(self):
        with self.assertRaises(ValueError):
            parse_intake_payload(
                {
                    "research_question": "测试",
                    "available_materials_choice": "A",
                    "intake_material_type": "papers_folder",
                }
            )

    def test_markdown_defaults_are_not_mislabeled_as_user_input(self):
        parsed = parse_markdown_intake_text("# 研究一个尚未填写表单的产业问题\n")
        self.assertEqual(parsed["available_materials_choice"], "A")
        self.assertEqual(parsed["evidence_policy"], "balanced")
        self.assertEqual(parsed["field_origin"]["available_materials_choice"], "system_default")
        self.assertEqual(parsed["field_origin"]["evidence_policy"], "system_default")
        self.assertTrue(parsed["default_accepted"]["available_materials_choice"])
        self.assertTrue(parsed["default_accepted"]["evidence_policy"])


if __name__ == "__main__":
    unittest.main()
