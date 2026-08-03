from __future__ import annotations

import unittest

from tools.maintenance.build_financial_field_catalog import (
    CatalogRow,
    _relationship,
    _wind_rows,
    render,
)


class FinancialFieldCatalogTests(unittest.TestCase):
    def test_wind_catalog_uses_verified_three_year_horizon(self) -> None:
        rows = _wind_rows()
        names = {row.feature_name for row in rows}
        self.assertEqual(len(rows), 99)
        self.assertIn("west_sales_fy3", names)
        self.assertIn("cash_pay_acq_const_fiolta", names)
        self.assertNotIn("west_sales_fy4", names)

    def test_unexplained_internal_factor_is_not_a_core_amount_input(self) -> None:
        row = CatalogRow(
            source="公司内网 Ricequant",
            interface="stock_analyst_consensus",
            feature_name="con_roe_yoy_2_180",
            description="Float32",
            market="A股",
            time_scope="未来",
            frequency="日频",
            status="期限未解释",
        )
        relation, utility = _relationship(row)
        self.assertIn("间接", relation)
        self.assertIn("当前不进入金额模型", utility)

    def test_yfinance_estimate_is_high_value_for_earnings_reconciliation(self) -> None:
        row = CatalogRow(
            source="yfinance/Yahoo Finance",
            interface="earnings_estimate",
            feature_name="earnings_estimate.avg",
            description="分析师预测",
            market="美股",
            time_scope="+1Y",
            frequency="截面",
            status="实测",
        )
        relation, utility = _relationship(row)
        self.assertIn("盈利预测直接", relation)
        self.assertIn("美股盈利对账核心", utility)

    def test_render_has_requested_columns(self) -> None:
        text = render(_wind_rows()[:1])
        for heading in (
            "原始 feature_name",
            "市场",
            "过去/未来与长度",
            "频率/更新方式",
            "与估值、盈利和公司财务建模的关系",
            "本课题有用性",
        ):
            self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()
