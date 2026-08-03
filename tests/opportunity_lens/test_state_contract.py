from __future__ import annotations

import unittest

from tools.opportunity_lens.state_registry import ENUMS, STATUS_FIELD_TO_ENUM
from tools.opportunity_lens.validators import (
    ValidationError,
    validate_no_forbidden_alias,
    validate_no_forbidden_public_fields,
    validate_state_transition,
    validate_status_field,
    validate_uri,
)


class StateContractTests(unittest.TestCase):
    def test_required_enums_exist(self):
        for enum_name in [
            "maturation_status",
            "score_grade",
            "score_status",
            "rating_status",
            "score_quality_label",
            "veto_code",
            "event_scope",
            "review_status",
            "replay_status",
            "evidence_policy",
            "intake_material_type",
            "policy_evidence_role",
            "policy_gate_verdict",
            "scoring_eligibility",
            "early_signal_strength_label",
        ]:
            self.assertIn(enum_name, ENUMS)

    def test_status_fields_are_registered(self):
        for field in ["run_status", "run_readiness_status", "maturation_status", "score_status"]:
            self.assertIn(field, STATUS_FIELD_TO_ENUM)
            self.assertEqual(validate_status_field(field, ENUMS[STATUS_FIELD_TO_ENUM[field]][0]), ENUMS[STATUS_FIELD_TO_ENUM[field]][0])

    def test_historical_aliases_rejected(self):
        with self.assertRaises(ValidationError):
            validate_no_forbidden_alias("maturation_status", "score_ready")
        with self.assertRaises(ValidationError):
            validate_status_field("candidate_stage", "screened")

    def test_polymorphic_transition_validation(self):
        self.assertEqual(validate_state_transition("run", "created", "intake_validated"), "intake_validated")
        with self.assertRaises(ValidationError):
            validate_state_transition("run", "completed", "scoring")
        self.assertEqual(validate_state_transition("audit_issue", "open", "waived"), "waived")

    def test_uri_contract(self):
        self.assertEqual(validate_uri("opp://source/1"), ("opp", "source", 1))
        self.assertEqual(validate_uri("opp://intake_contract/1"), ("opp", "intake_contract", 1))
        self.assertEqual(validate_uri("opp://early_signal/1"), ("opp", "early_signal", 1))
        self.assertEqual(validate_uri("ab://research.source/1"), ("ab", "research.source", 1))
        with self.assertRaises(ValidationError):
            validate_uri("file://tools/dynamic/secrets/x")

    def test_public_payload_rejects_legacy_names(self):
        with self.assertRaises(ValidationError):
            validate_no_forbidden_public_fields({"question": "bad"})
        with self.assertRaises(ValidationError):
            validate_no_forbidden_public_fields({"nested": {"available_materials_state": "A"}})


if __name__ == "__main__":
    unittest.main()
