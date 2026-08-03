from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class Run16ViewerHierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = (ROOT / "tools/viewer/static/opportunity_lens_v2.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "tools/viewer/static/opportunity_lens_v2.css").read_text(encoding="utf-8")

    def test_deep_research_section_keys_receive_card_layout(self) -> None:
        self.assertIn('[data-opp-section-key^="ai_application_subsectors"]', self.script)
        self.assertIn('[data-opp-section-key^="ai_application_companies"]', self.script)

    def test_company_heading_exposes_name_subsector_and_status(self) -> None:
        for class_name in (
            "opp-company-name",
            "opp-company-subsector",
            "opp-company-status",
        ):
            self.assertIn(class_name, self.script)
            self.assertIn("." + class_name, self.styles)

    def test_industry_and_company_sections_have_distinct_cards(self) -> None:
        for class_name in (
            ".opp-research-card--industry",
            ".opp-research-card--company-group",
            ".opp-company-research-card",
            ".opp-research-heading-title",
        ):
            self.assertIn(class_name, self.styles)


if __name__ == "__main__":
    unittest.main()
