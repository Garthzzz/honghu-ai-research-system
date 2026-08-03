from __future__ import annotations

import unittest
from pathlib import Path

from tools.opportunity_lens.playwright_table_audit import (
    _factor_label_issues,
    _raw_math_markers,
    _raw_machine_date_issues,
)


class PlaywrightTableAuditTests(unittest.TestCase):
    def test_raw_machine_date_fragments_are_blocking_item_issues(self) -> None:
        issues = _raw_machine_date_issues(["2022-04", "2022-04", "2021-11"])

        self.assertEqual(len(issues), 1)
        self.assertIn("2022-04", issues[0])
        self.assertIn("2021-11", issues[0])
        self.assertEqual(issues[0].count("2022-04"), 1)

    def test_humanized_drawer_dates_do_not_create_issues(self) -> None:
        self.assertEqual(_raw_machine_date_issues([]), [])

    def test_visible_raw_latex_is_a_blocking_browser_issue(self) -> None:
        text = r"$$ S_i=\operatorname{clip}(\frac{x}{y}),\qquad i\in\mathcal{A} $$"

        self.assertEqual(
            _raw_math_markers(text),
            ["$$", "\\operatorname", "\\frac", "\\mathcal", "\\qquad"],
        )

    def test_rendered_human_text_has_no_raw_math_markers(self) -> None:
        self.assertEqual(_raw_math_markers("基础权重乘以公司质量调整，再按上限归一化。"), [])

    def test_katex_is_bundled_for_offline_viewer(self) -> None:
        root = Path(__file__).resolve().parents[2]
        template = (root / "tools/viewer/templates/base.html").read_text(encoding="utf-8")
        self.assertNotIn("cdn.jsdelivr.net/npm/katex", template)
        self.assertNotIn("'opp-page'", template)
        for relative in (
            "tools/viewer/static/vendor/katex-0.16.9/katex.min.css",
            "tools/viewer/static/vendor/katex-0.16.9/katex.min.js",
            "tools/viewer/static/vendor/katex-0.16.9/contrib/auto-render.min.js",
            "tools/viewer/static/vendor/katex-0.16.9/fonts/KaTeX_Main-Regular.woff2",
        ):
            self.assertTrue((root / relative).is_file(), relative)

    def test_clipped_squeezed_or_overlapping_factor_labels_are_blocking(self) -> None:
        issues = _factor_label_issues(
            [
                {"text": "下游价格动量", "clipped": True},
                {"text": "12 个月产能事件", "squeezed": True},
                {"text": "客户资本开支/产能信号", "score_overlap": True},
            ]
        )

        self.assertEqual(len(issues), 3)
        self.assertIn("被裁切", issues[0])
        self.assertIn("可用宽度过窄", issues[1])
        self.assertIn("分数徽标重叠", issues[2])

    def test_readable_factor_labels_do_not_create_issues(self) -> None:
        self.assertEqual(
            _factor_label_issues(
                [{"text": "下游价格动量", "clipped": False, "squeezed": False, "score_overlap": False}]
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
