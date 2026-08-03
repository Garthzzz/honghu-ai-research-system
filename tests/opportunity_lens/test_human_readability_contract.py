from __future__ import annotations

import unittest
from pathlib import Path

from tools.opportunity_lens.factor_dictionary import FACTORS
from tools.opportunity_lens.read_models import _value_display
from tools.opportunity_lens.value_display import format_data_point_value


class HumanReadabilityContractTests(unittest.TestCase):
    def test_every_standalone_evidence_button_page_has_a_drawer(self):
        template_root = Path(__file__).resolve().parents[2] / "tools/viewer/templates/opportunity_lens"
        for name in ("audit.html", "supplement.html"):
            with self.subTest(template=name):
                text = (template_root / name).read_text(encoding="utf-8")
                self.assertIn("data-opp-evidence", text)
                self.assertIn("data-opp-drawer", text)
                self.assertIn("data-opp-drawer-body", text)

    def test_every_factor_has_human_metadata(self):
        for factor in FACTORS:
            self.assertTrue(factor.label)
            self.assertTrue(factor.formula)
            self.assertTrue(factor.description)
            self.assertTrue(factor.human_question)
            self.assertNotEqual(factor.code, factor.label)
            self.assertNotIn(".", factor.label)

    def test_cny_amount_uses_source_bound_usd_equivalent(self):
        row = {
            "value_num": 382.40,
            "unit": "亿元人民币",
            "source_excerpt": (
                "结构化快照：总市值10923.28亿元人民币"
                "（约1611.86亿美元）。"
            ),
        }
        self.assertEqual(
            _value_display(row),
            "382.4亿元人民币（约56.43亿美元）",
        )

    def test_cny_amount_without_source_fx_does_not_invent_conversion(self):
        row = {"value_num": 382.40, "unit": "亿元人民币"}
        self.assertEqual(_value_display(row), "382.4亿元人民币")

    def test_cny_amount_uses_explicit_snapshot_fx_for_negative_value(self):
        row = {
            "value_num": -192.73,
            "unit": "亿元人民币",
            "source_excerpt": (
                "本轮美元等值按1美元=6.7768元人民币换算："
                "-192.73亿元人民币（约-28.44亿美元）。"
            ),
        }
        self.assertEqual(
            _value_display(row),
            "-192.73亿元人民币（约-28.44亿美元）",
        )

    def test_time_series_is_rendered_as_readable_sequence(self):
        row = {
            "value_text": (
                '{"kind":"time_series_data_point","unit":"%","observation_count":3,'
                '"observations":[{"period":"2023","value_num":71.23},'
                '{"period":"2024","value_num":87.63},'
                '{"period":"2025","value_num":82.11}]}'
            ),
            "unit": "%",
        }
        display = format_data_point_value(row)
        self.assertEqual(display, "2023：71.23%；2024：87.63%；2025：82.11%")
        self.assertNotIn("{", display)
        self.assertNotIn("observation_count", display)

    def test_composite_time_series_fields_are_humanized(self):
        row = {
            "value_text": (
                '{"kind":"time_series_data_point","unit":"复合时间序列",'
                '"observations":[{"period":"2025",'
                '"value_text":"capacity_wafers_per_year=3670000；utilization_pct=75.18"}]}'
            ),
            "unit": "复合时间序列",
        }
        self.assertEqual(
            format_data_point_value(row),
            "2025：年产能（片/年） 3670000；产能利用率 75.18%",
        )

    def test_human_text_does_not_repeat_compound_currency_unit(self):
        row = {
            "value_text": "198.90亿元人民币（约29.46亿美元）",
            "unit": "亿元人民币/亿美元",
        }
        self.assertEqual(
            format_data_point_value(row),
            "198.90亿元人民币（约29.46亿美元）",
        )

    def test_human_text_does_not_repeat_multiple_unit(self):
        row = {"value_text": "市净率为1.23倍", "unit": "倍"}
        self.assertEqual(format_data_point_value(row), "市净率为1.23倍")

    def test_numeric_value_still_appends_unit(self):
        self.assertEqual(format_data_point_value({"value_num": 12.5, "unit": "%"}), "12.5%")

    def test_qualified_financial_unit_is_not_repeated(self):
        row = {
            "value_text": "收入8.20亿元人民币；资本开支0.76亿元人民币；毛利率18.5%",
            "unit": "亿元人民币，比例除外",
        }
        self.assertEqual(
            format_data_point_value(row),
            "收入8.20亿元人民币；资本开支0.76亿元人民币；毛利率18.5%",
        )

    def test_qualitative_units_are_not_appended_to_prose(self):
        for unit in ("定性", "事实", "qualitative", "多指标"):
            with self.subTest(unit=unit):
                self.assertEqual(
                    format_data_point_value({"value_text": "已进入批量销售阶段", "unit": unit}),
                    "已进入批量销售阶段",
                )

    def test_formula_equals_sign_is_preserved(self):
        row = {
            "value_text": "21.83÷(1+0.39892)=15.6049元",
            "unit": "文本",
        }
        self.assertEqual(
            format_data_point_value(row),
            "21.83÷(1+0.39892)=15.6049元",
        )

    def test_latin_currency_unit_has_readable_spacing(self):
        self.assertEqual(
            format_data_point_value({"value_num": 25.54, "unit": "EUR 百万"}),
            "25.54 EUR 百万",
        )

    def test_multi_metric_unit_is_not_repeated(self):
        row = {
            "value_text": "收入5.92亿欧元；自由现金流0.63亿欧元；毛利率16.3%",
            "unit": "亿欧元、%",
        }
        self.assertEqual(
            format_data_point_value(row),
            "收入5.92亿欧元；自由现金流0.63亿欧元；毛利率16.3%",
        )


if __name__ == "__main__":
    unittest.main()
