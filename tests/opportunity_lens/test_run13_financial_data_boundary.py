from __future__ import annotations

import unittest

from tools.opportunity_lens.run13_pack_builder import (
    DYNAMIC_FINANCIAL_SOURCE_REFS,
    build_pack,
)


class Run13FinancialDataBoundaryTest(unittest.TestCase):
    def test_vendor_financial_rows_are_not_duplicated_into_c_track_pack(self) -> None:
        pack = build_pack()
        source_refs = {str(row["ref"]) for row in pack["sources"]}
        claim_refs = {str(row["source_ref"]) for row in pack["claims"]}
        point_refs = {str(row["source_ref"]) for row in pack["data_points"]}
        self.assertTrue(DYNAMIC_FINANCIAL_SOURCE_REFS.isdisjoint(source_refs))
        self.assertTrue(DYNAMIC_FINANCIAL_SOURCE_REFS.isdisjoint(claim_refs))
        self.assertTrue(DYNAMIC_FINANCIAL_SOURCE_REFS.isdisjoint(point_refs))

        blocked_uris = {
            f"source_ref:{ref}" for ref in DYNAMIC_FINANCIAL_SOURCE_REFS
        }
        public_rows = [
            *pack["sections"],
            *pack["entity_sections"],
            *pack["entity_investment_targets"],
        ]
        for row in public_rows:
            self.assertTrue(
                blocked_uris.isdisjoint(
                    set(row.get("evidence_ref_uri_list") or [])
                )
            )
        self.assertEqual(
            pack["financial_data_boundary"]["database"],
            "financial.db",
        )


if __name__ == "__main__":
    unittest.main()
