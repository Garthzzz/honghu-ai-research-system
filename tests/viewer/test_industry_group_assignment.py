from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from tools.viewer import app as viewer
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

    def test_overview_reads_postgresql_projection_not_legacy_main_view(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE industry (
                id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER,
                tier INTEGER, status TEXT, core_dynamic TEXT, last_updated TEXT
            );
            CREATE TABLE source_entity (entity_type TEXT, entity_id TEXT);
            CREATE TABLE industry_data_point (industry_id INTEGER);
            CREATE TABLE company_industry (industry_id INTEGER, company_id INTEGER);
            CREATE TABLE thesis (industry_id INTEGER, status TEXT);
            INSERT INTO industry VALUES
                (6, '通信', NULL, 1, '深度跟踪', '', '2026-08-18');
            CREATE VIEW v_industry_overview AS SELECT * FROM industry;
            CREATE TEMP TABLE industry AS SELECT * FROM main.industry;
            INSERT INTO temp.industry VALUES
                (50, '光纤', NULL, 1, '深度跟踪', '', '2026-08-19');
            INSERT INTO company_industry VALUES (50, 199), (50, 200);
            """
        )

        self.assertEqual(
            [row[0] for row in connection.execute(
                "SELECT id FROM main.v_industry_overview ORDER BY id"
            )],
            [6],
        )
        with mock.patch.object(
            viewer, "_request_read_connection", return_value=(connection, False)
        ):
            rows = viewer._industry_overview_rows()

        self.assertEqual([row["id"] for row in rows], [50, 6])
        fiber = next(row for row in rows if row["id"] == 50)
        self.assertEqual(fiber["company_count"], 2)
        connection.close()

    def test_research_home_and_navigation_use_current_overview_rows(self) -> None:
        fiber = {
            "id": 50,
            "name": "光纤",
            "parent_id": None,
            "tier": 1,
            "status": "深度跟踪",
            "core_dynamic": "光纤行业研究",
            "last_updated": "2026-08-19",
            "source_count": 30,
            "data_point_count": 120,
            "company_count": 8,
            "active_thesis_count": 0,
        }
        hero = {
            "has_md": True,
            "last_updated": "2026-08-19",
            "core_judgment": "独立光纤行业",
            "conclusions": [],
        }

        with viewer.app.test_request_context("/research"):
            with (
                mock.patch.object(
                    viewer, "_industry_overview_rows", return_value=[fiber]
                ) as overview,
                mock.patch.object(viewer, "query_all", return_value=[]),
                mock.patch.object(viewer, "query_one", return_value={"n": 0}),
                mock.patch.object(viewer, "load_q5_hero_for", return_value=hero),
                mock.patch.object(viewer, "find_industry_md", return_value=None),
                mock.patch.object(
                    viewer, "render_template", side_effect=lambda _name, **ctx: ctx
                ),
            ):
                context = viewer.research_home()
                navigation = viewer.inject_nav()

        self.assertEqual([row["id"] for row in context["industries"]], [50])
        ai_sector = next(
            group for group in context["sector_groups"]
            if group["name"] == "AI算力与半导体产业链"
        )
        self.assertEqual([row["id"] for row in ai_sector["deep_cards"]], [50])
        self.assertEqual([row["id"] for row in navigation["nav_industries"]], [50])
        self.assertEqual(overview.call_count, 2)


if __name__ == "__main__":
    unittest.main()
