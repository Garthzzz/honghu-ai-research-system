from __future__ import annotations

import unittest

from tools.research_core.modeling_benchmark import benchmark


class ModelingBenchmarkTests(unittest.TestCase):
    def test_progressive_loading_keeps_simple_tasks_light_and_complex_task_complete(self) -> None:
        result = benchmark(iterations=2)
        rows = {row["case"]: row for row in result["cases"]}
        self.assertEqual(rows["普通盈利公司未来利润"]["selected_skill_count"], 1)
        self.assertEqual(rows["单纯证据核验"]["selected_skill_count"], 0)
        self.assertEqual(rows["外部竞争冲击"]["selected_skill_count"], 4)
        self.assertGreater(rows["普通盈利公司未来利润"]["context_reduction_pct"], 0)
        self.assertEqual(rows["纯行业市场空间"]["report_search_task_count"], rows["纯行业市场空间"]["web_search_task_count"])
        self.assertEqual(rows["单纯证据核验"]["second_round_search_task_count"], 0)


if __name__ == "__main__":
    unittest.main()
