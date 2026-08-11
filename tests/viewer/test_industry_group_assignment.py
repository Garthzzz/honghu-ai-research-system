from __future__ import annotations

import unittest

from tools.viewer.app import _derive_industry_group_assignments


class IndustryGroupAssignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            {"id": 1, "name": "anchor_a", "parent_id": None},
            {"id": 2, "name": "child_a", "parent_id": 1},
            {"id": 3, "name": "grandchild_a", "parent_id": 2},
            {"id": 4, "name": "anchor_b", "parent_id": None},
            {"id": 5, "name": "peer_a", "parent_id": None},
            {"id": 6, "name": "candidate", "parent_id": None},
            {"id": 7, "name": "peer_b", "parent_id": None},
        ]
        self.groups = {
            "group_a": {"industries": ["anchor_a", "peer_a"]},
            "group_b": {"industries": ["anchor_b", "peer_b"]},
        }

    def test_parent_assignment_is_inherited_recursively(self) -> None:
        assignments = _derive_industry_group_assignments(self.rows, self.groups)

        self.assertEqual(assignments["child_a"], "group_a")
        self.assertEqual(assignments["grandchild_a"], "group_a")

    def test_two_independent_relation_votes_assign_candidate(self) -> None:
        relations = [
            {"upstream_id": 6, "downstream_id": 1},
            {"upstream_id": 6, "downstream_id": 5},
        ]

        assignments = _derive_industry_group_assignments(
            self.rows,
            self.groups,
            relations=relations,
            eligible_names={"candidate"},
        )

        self.assertEqual(assignments["candidate"], "group_a")

    def test_single_vote_tie_and_empty_eligibility_do_not_infer(self) -> None:
        single_vote = [{"upstream_id": 6, "downstream_id": 1}]
        tied_votes = [
            {"upstream_id": 6, "downstream_id": 1},
            {"upstream_id": 6, "downstream_id": 5},
            {"upstream_id": 6, "downstream_id": 4},
            {"upstream_id": 6, "downstream_id": 7},
        ]

        self.assertNotIn(
            "candidate",
            _derive_industry_group_assignments(
                self.rows,
                self.groups,
                relations=single_vote,
                eligible_names={"candidate"},
            ),
        )
        self.assertNotIn(
            "candidate",
            _derive_industry_group_assignments(
                self.rows,
                self.groups,
                relations=tied_votes,
                eligible_names={"candidate"},
            ),
        )
        self.assertNotIn(
            "candidate",
            _derive_industry_group_assignments(
                self.rows,
                self.groups,
                relations=[
                    {"upstream_id": 6, "downstream_id": 1},
                    {"upstream_id": 6, "downstream_id": 5},
                ],
                eligible_names=set(),
            ),
        )

    def test_duplicate_relation_does_not_manufacture_two_votes(self) -> None:
        duplicate_relation = [
            {"upstream_id": 6, "downstream_id": 1},
            {"upstream_id": 6, "downstream_id": 1},
        ]

        assignments = _derive_industry_group_assignments(
            self.rows,
            self.groups,
            relations=duplicate_relation,
            eligible_names={"candidate"},
        )

        self.assertNotIn("candidate", assignments)


if __name__ == "__main__":
    unittest.main()
