from __future__ import annotations

import json
import math
import sys
import types
import unittest
from unittest import mock

import pandas as pd

from tools.opportunity_lens.collect_byd_luxshare_financial_snapshot import (
    _jsonable,
    _reconcile_bps_basis_in_place,
)
import company_financial_series_utils as financial_series


class BydLuxshareFinancialSnapshotTests(unittest.TestCase):
    def test_bps_basis_reconciliation_flags_corporate_action_mismatch(self):
        snapshot = {
            "companies": {
                "eoptolink": {
                    "market_snapshot": {
                        "price": 482.88,
                        "pb": 33.04,
                        "bps_mrq": 20.50,
                        "trade_date": "2026-07-17",
                        "financial_metrics_as_of": "2026-03-31",
                    }
                }
            }
        }
        _reconcile_bps_basis_in_place(snapshot)
        market = snapshot["companies"]["eoptolink"]["market_snapshot"]
        self.assertAlmostEqual(market["bps_current_share_basis_implied"], 14.615012, 6)
        reconciliation = market["bps_basis_reconciliation"]
        self.assertAlmostEqual(reconciliation["relative_difference_pct"], 40.2667, 4)
        self.assertEqual(
            reconciliation["status"],
            "reporting_period_share_basis_not_reconciled_to_market_pb",
        )
        self.assertFalse(reconciliation["direct_current_pb_recalculation_allowed"])
        self.assertIn("不是独立抓取", reconciliation["provenance"])

    def test_bps_basis_reconciliation_accepts_small_difference_and_handles_zero_pb(self):
        snapshot = {
            "companies": {
                "consistent": {
                    "market_snapshot": {
                        "price": 100,
                        "pb": 5,
                        "bps_mrq": 20.4,
                        "trade_date": "2026-07-17",
                    }
                },
                "zero_pb": {
                    "market_snapshot": {
                        "price": 100,
                        "pb": 0,
                        "bps_mrq": 20,
                        "trade_date": "2026-07-17",
                    }
                },
                "reported_missing": {
                    "market_snapshot": {
                        "price": 100,
                        "pb": 5,
                        "bps_mrq": 20,
                        "trade_date": "2026-07-17",
                        "bps_basis_reconciliation": {
                            "reported_bps": None,
                            "status": "reported_bps_missing_used_current_price_over_pb",
                        },
                    }
                },
            }
        }
        _reconcile_bps_basis_in_place(snapshot)
        consistent = snapshot["companies"]["consistent"]["market_snapshot"]
        self.assertEqual(
            consistent["bps_basis_reconciliation"]["status"],
            "consistent_with_current_pb_within_3pct",
        )
        self.assertTrue(
            consistent["bps_basis_reconciliation"]
            ["direct_current_pb_recalculation_allowed"]
        )
        zero_pb = snapshot["companies"]["zero_pb"]["market_snapshot"]
        self.assertIsNone(zero_pb["bps_current_share_basis_implied"])
        self.assertIsNone(
            zero_pb["bps_basis_reconciliation"]["relative_difference_pct"]
        )
        reported_missing = snapshot["companies"]["reported_missing"][
            "market_snapshot"
        ]
        self.assertEqual(
            reported_missing["bps_basis_reconciliation"]["status"],
            "reported_bps_missing_price_over_pb_only",
        )
        self.assertIsNone(
            reported_missing["bps_basis_reconciliation"]["reported_bps"]
        )

    def test_non_finite_values_become_null_recursively(self):
        result = _jsonable(
            {
                "nan": float("nan"),
                "positive_infinity": float("inf"),
                "negative_infinity": float("-inf"),
                "nested": [1.0, {"finite": 2.5}],
            }
        )
        self.assertIsNone(result["nan"])
        self.assertIsNone(result["positive_infinity"])
        self.assertIsNone(result["negative_infinity"])
        self.assertTrue(math.isfinite(result["nested"][1]["finite"]))
        serialized = json.dumps(result, allow_nan=False)
        self.assertNotIn("NaN", serialized)
        self.assertNotIn("Infinity", serialized)

    def test_tushare_series_covers_2018_and_balance_sheet_fields(self):
        with (
            mock.patch.object(
                financial_series,
                "fetch_income_rows",
                return_value=[
                    {
                        "end_date": "20180331",
                        "ann_date": "20180420",
                        "total_revenue": 1_000_000_000,
                        "n_income_attr_p": 100_000_000,
                        "rd_exp": 20_000_000,
                        "update_flag": "1",
                    }
                ],
            ),
            mock.patch.object(
                financial_series,
                "fetch_fina_indicator_rows",
                return_value=[
                    {
                        "end_date": "20180331",
                        "ann_date": "20180420",
                        "grossprofit_margin": 20,
                        "netprofit_margin": 10,
                        "roe": 3,
                        "roa": 2,
                        "update_flag": "1",
                    }
                ],
            ),
            mock.patch.object(
                financial_series,
                "fetch_cashflow_rows",
                return_value=[
                    {
                        "end_date": "20180331",
                        "ann_date": "20180420",
                        "n_cashflow_act": 80_000_000,
                        "c_pay_acq_const_fiolta": 30_000_000,
                        "update_flag": "1",
                    }
                ],
            ),
            mock.patch.object(
                financial_series,
                "fetch_balancesheet_rows",
                return_value=[
                    {
                        "end_date": "20180331",
                        "ann_date": "20180420",
                        "total_assets": 2_000_000_000,
                        "accounts_receiv": 300_000_000,
                        "inventories": 400_000_000,
                        "fix_assets": 500_000_000,
                        "cip": 60_000_000,
                        "contract_liab": 70_000_000,
                        "total_hldr_eqy_exc_min_int": 900_000_000,
                        "update_flag": "1",
                    }
                ],
            ),
            mock.patch.object(
                financial_series,
                "fetch_stock_company_latest",
                return_value={"employees": "1234", "main_business": "test"},
            ),
        ):
            result = financial_series._from_tushare(
                "300308.SZ", {"CNY": 1.0, "USD": 7.0}
            )
        self.assertEqual(len(financial_series.TARGET_END_DATES), 33)
        row = result["periods"][0]
        self.assertEqual(row["period"], "2018Q1")
        self.assertEqual(row["statement_basis"], "year_to_date_cumulative")
        self.assertEqual(row["fixed_assets"]["cny_yi"], 5.0)
        self.assertEqual(row["construction_in_progress"]["cny_yi"], 0.6)
        self.assertEqual(row["contract_liabilities"]["cny_yi"], 0.7)
        self.assertEqual(result["employee_snapshot"]["employees"], 1234)
        self.assertIn("2018Q2", result["coverage"]["missing_periods"])

    def test_yfinance_series_maps_quarterly_balance_and_discloses_source_limit(self):
        annual_income = pd.DataFrame(
            {pd.Timestamp("2025-12-31"): {"TotalRevenue": 2_000_000_000, "NetIncome": 200_000_000}}
        )
        quarterly_income = pd.DataFrame(
            {pd.Timestamp("2025-03-31"): {"TotalRevenue": 400_000_000, "NetIncome": 40_000_000}}
        )
        annual_cash = pd.DataFrame(
            {pd.Timestamp("2025-12-31"): {"OperatingCashFlow": 300_000_000, "CapitalExpenditure": -100_000_000}}
        )
        quarterly_cash = pd.DataFrame(
            {pd.Timestamp("2025-03-31"): {"OperatingCashFlow": 50_000_000, "CapitalExpenditure": -20_000_000}}
        )
        annual_balance = pd.DataFrame(
            {pd.Timestamp("2025-12-31"): {"TotalAssets": 5_000_000_000, "StockholdersEquity": 2_000_000_000}}
        )
        quarterly_balance = pd.DataFrame(
            {
                pd.Timestamp("2025-03-31"): {
                    "TotalAssets": 4_000_000_000,
                    "Inventory": 600_000_000,
                    "NetPPE": 900_000_000,
                    "StockholdersEquity": 1_800_000_000,
                }
            }
        )

        class FakeTicker:
            def get_info(self):
                return {"financialCurrency": "HKD", "fullTimeEmployees": 9876}

            def get_income_stmt(self, freq: str):
                return annual_income if freq == "yearly" else quarterly_income

            def get_cashflow(self, freq: str):
                return annual_cash if freq == "yearly" else quarterly_cash

            def get_balance_sheet(self, freq: str):
                return annual_balance if freq == "yearly" else quarterly_balance

        with mock.patch.dict(
            sys.modules, {"yfinance": types.SimpleNamespace(Ticker=lambda symbol: FakeTicker())}
        ):
            result = financial_series._from_yfinance(
                "0285.HK", {"HKD": 0.92, "USD": 7.0}
            )
        q1 = next(row for row in result["periods"] if row["period"] == "2025Q1")
        self.assertEqual(q1["statement_basis"], "single_quarter")
        self.assertEqual(q1["inventory"]["local_yi"], 6.0)
        self.assertEqual(q1["fixed_assets"]["cny_yi"], 8.28)
        self.assertEqual(result["employee_snapshot"]["employees"], 9876)
        self.assertIn("无法满足 2018 年以来完整历史", result["coverage"]["source_limitations"])


if __name__ == "__main__":
    unittest.main()
