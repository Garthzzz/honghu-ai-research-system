from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.opportunity_lens.artifact_freeze import (
    build_artifact_freeze,
    sha256_bytes,
    sha256_text,
)
from tools.opportunity_lens.browser_audit_contract import (
    BROWSER_AUDIT_SCHEMA_VERSION,
    BROWSER_AUDIT_SCRIPT_VERSION,
    EVIDENCE_DRAWER_RULE_VERSION,
    browser_audit_manifest_hash,
    detect_raw_machine_date_fragments,
    expected_public_routes,
    record_browser_visual_audit,
    validate_browser_visual_audit,
)
from tools.opportunity_lens.constants import RUN_PACK_SCHEMA_VERSION
from tools.opportunity_lens.db import connect
from tools.opportunity_lens.migrate import init_db
from tools.opportunity_lens.publication import evaluate_publication_gate, publish_run
from tools.opportunity_lens.review_workflow import record_agent_review, record_quality_gate
from tools.research_core.config import resolve_track_config


class ArtifactFreezePublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.db_path = self.root / "data" / "opportunity_lens.db"
        for relative, content in {
            "tools/viewer/app.py": "APP_VERSION = 1\n",
            "tools/viewer/templates/run.html": "<main>run</main>\n",
            "tools/viewer/static/opportunity_lens.css": ".opp-page { overflow: hidden; }\n",
            "tools/viewer/static/opportunity_lens.js": "window.viewerVersion = 1;\n",
            "tools/opportunity_lens/read_models.py": "DISPLAY_VERSION = 1\n",
        }.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        init_db(self.db_path)
        self.conn = connect(self.db_path)
        self.run_id = int(
            self.conn.execute(
                """
                INSERT INTO opportunity_run(
                  question,research_question,run_mode,run_status,run_readiness_status,
                  evidence_policy,schema_version,api_contract_version,score_rule_version,
                  source_tier_version,search_protocol_version,report_template_version,pdf_export_version
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "测试当前产物冻结",
                    "测试当前产物冻结",
                    "c_open",
                    "under_review",
                    "reviewable",
                    "balanced",
                    "schema.test",
                    "api.test",
                    "score.test",
                    "source.test",
                    "search.test",
                    "report.test",
                    "pdf.test",
                ),
            ).lastrowid
        )
        self.entity_id = int(
            self.conn.execute(
                """
                INSERT INTO opportunity_entity(entity_type,taxonomy_level,canonical_name,display_name)
                VALUES('segment','segment','browser-route-test','浏览器路由测试对象')
                """
            ).lastrowid
        )
        self.conn.execute(
            """
            INSERT INTO opportunity_entity_maturation(run_id,entity_id,maturation_status)
            VALUES(?,?,?)
            """,
            (self.run_id, self.entity_id, "review_ready"),
        )
        score_batch_id = int(
            self.conn.execute(
                """
                INSERT INTO opportunity_score_batch(run_id,score_rule_version,score_batch_status,is_current)
                VALUES(?,?,?,1)
                """,
                (self.run_id, "score.test", "completed"),
            ).lastrowid
        )
        self.factor_ids = []
        self.slot_ids = []
        for index in range(2):
            factor_code = f"test.factor.{index + 1}"
            self.factor_ids.append(
                int(
                    self.conn.execute(
                        """
                        INSERT INTO opportunity_factor_score(
                          run_id,score_batch_id,entity_id,factor_code,score_status,
                          coverage,confidence,coverage_multiplier,confidence_multiplier,
                          audit_multiplier,reliability_multiplier,factor_trace_json,is_current
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)
                        """,
                        (
                            self.run_id,
                            score_batch_id,
                            self.entity_id,
                            factor_code,
                            "complete",
                            1.0,
                            1.0,
                            1.0,
                            1.0,
                            1.0,
                            1.0,
                            "{}",
                        ),
                    ).lastrowid
                )
            )
            self.slot_ids.append(
                int(
                    self.conn.execute(
                        """
                        INSERT INTO opportunity_metric_slot(
                          run_id,entity_id,factor_code,slot_key,metric_slot_status,
                          value_status,slot_weight,slot_confidence
                        ) VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (
                            self.run_id,
                            self.entity_id,
                            factor_code,
                            f"test_slot_{index + 1}",
                            "used_in_factor",
                            "available",
                            1.0,
                            1.0,
                        ),
                    ).lastrowid
                )
            )
        self.pack_hash = self._insert_pack_manifest(b'{"pack":"v1"}')
        for gate_name in resolve_track_config("c").get("review", {}).get("deterministic_gates", []):
            record_quality_gate(
                self.conn,
                self.run_id,
                gate_name,
                "GREEN",
                gate_version="research.workflow.v2",
            )
        self.freeze = build_artifact_freeze(self.conn, self.run_id, project_root=self.root)
        self.browser_manifest = self._browser_manifest(self.freeze)
        self.browser_manifest_hash = record_browser_visual_audit(
            self.conn,
            self.run_id,
            self.browser_manifest,
            project_root=self.root,
        )
        self._record_current_reviews()
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def _insert_pack_manifest(self, content: bytes) -> str:
        cache_path = self.root / "cache" / "research_content" / f"pack_{len(content)}_{content[-2:].hex()}.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
        pack_hash = sha256_bytes(content)
        payload = {
            "pack_slug": "artifact-freeze-test",
            "pack_hash": pack_hash,
            "pack_schema_version": RUN_PACK_SCHEMA_VERSION,
            "workflow_contract_version": "research.workflow.v2",
            "content_cache": {
                "hash": pack_hash,
                "path": str(cache_path),
            },
        }
        self.conn.execute(
            """
            INSERT INTO opportunity_run_manifest(
              run_id,manifest_type,manifest_json,manifest_hash,
              workflow_contract_version,pack_schema_version
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                self.run_id,
                "manual_research_pack",
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
                "research.workflow.v2",
                RUN_PACK_SCHEMA_VERSION,
            ),
        )
        return pack_hash

    def _geometry(self) -> dict:
        return {
            "left": 10.0,
            "right": 90.0,
            "top": 10.0,
            "bottom": 30.0,
            "width": 80.0,
            "height": 20.0,
            "container_left": 0.0,
            "container_right": 100.0,
            "fully_visible": True,
            "clipped": False,
        }

    def _edge(self, *, right: bool, mobile: bool) -> dict:
        maximum = 0.0 if mobile else 20.0
        return {
            "scroll_left": maximum if right else 0.0,
            "max_scroll_left": maximum,
            "reached": True,
            "container_geometry": {
                "left": 0.0,
                "right": 100.0,
                "top": 0.0,
                "bottom": 100.0,
                "width": 100.0,
                "height": 100.0,
            },
        }

    def _browser_manifest(self, freeze) -> dict:
        routes = expected_public_routes(self.conn, self.run_id)
        viewports = {}
        for viewport_name, dimensions in {
            "desktop": {"width": 1440, "height": 1000},
            "mobile": {"width": 390, "height": 844},
        }.items():
            table = {
                "index": 0,
                "row_count": 1,
                "column_count": 2,
                "keyboard_reachable": True,
                "left_edge": self._edge(right=False, mobile=viewport_name == "mobile"),
                "right_edge": self._edge(right=True, mobile=viewport_name == "mobile"),
                "rightmost_column": {
                    "header_text": "结论",
                    "header_geometry": self._geometry(),
                    "cell_geometries": [self._geometry()],
                },
                "issues": [],
            }
            route_results = []
            for route_index, route in enumerate(routes):
                screenshot = self.root / "cache" / "browser" / f"{viewport_name}_{route_index}.png"
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                screenshot.write_bytes(
                    b"\x89PNG\r\n\x1a\n"
                    + f"fake-{viewport_name}-{route_index}-png".encode("utf-8")
                )
                table_screenshot = (
                    self.root / "cache" / "browser" / f"{viewport_name}_{route_index}_table.png"
                )
                table_screenshot.write_bytes(
                    b"\x89PNG\r\n\x1a\n"
                    + f"fake-{viewport_name}-{route_index}-table-png".encode("utf-8")
                )
                table_result = json.loads(json.dumps(table))
                table_result["right_edge_screenshot_ref"] = table_screenshot.relative_to(
                    self.root
                ).as_posix()
                table_result["right_edge_screenshot_hash"] = sha256_bytes(
                    table_screenshot.read_bytes()
                )
                drawer_screenshot = (
                    self.root / "cache" / "browser" / f"{viewport_name}_{route_index}_drawer.png"
                )
                drawer_screenshot.write_bytes(
                    b"\x89PNG\r\n\x1a\n"
                    + f"fake-{viewport_name}-{route_index}-drawer-png".encode("utf-8")
                )
                drawer_items = []
                for item_index, activation_key in enumerate(("Enter", "Space")):
                    drawer_items.append(
                        {
                            "reference_hash": sha256_text(
                                f"{viewport_name}:{route}:reference:{item_index}"
                            ),
                            "activation_key": activation_key,
                            "button_focused": True,
                            "api_status": 200,
                            "drawer_visible": True,
                            "drawer_horizontal_overflow_px": 0,
                            "headline": f"证据说明 {item_index + 1}",
                            "drawer_text_hash": sha256_text(
                                f"{viewport_name}:{route}:drawer-text:{item_index}"
                            ),
                            "forbidden_fragments": [],
                            "raw_machine_date_fragments": [],
                            "raw_source_level_code_fragments": [],
                            "raw_json_visible": False,
                            "human_content_checked": True,
                            "issues": [],
                        }
                    )
                route_results.append({
                    "route": route,
                    "status": 200,
                    "table_count": 1,
                    "global_overflow_px": 0,
                    "tables": [table_result],
                    "evidence_drawer": {
                        "content_rule_version": EVIDENCE_DRAWER_RULE_VERSION,
                        "button_count": 2,
                        "unique_reference_count": 2,
                        "tested_reference_count": 2,
                        "items": drawer_items,
                        "drawer_screenshot_ref": drawer_screenshot.relative_to(
                            self.root
                        ).as_posix(),
                        "drawer_screenshot_hash": sha256_bytes(drawer_screenshot.read_bytes()),
                        "issues": [],
                    },
                    "screenshot_ref": screenshot.relative_to(self.root).as_posix(),
                    "screenshot_hash": sha256_bytes(screenshot.read_bytes()),
                    "screenshot_full_page": True,
                    "issues": [],
                })
            viewports[viewport_name] = {
                "viewport": dimensions,
                "route_count": len(route_results),
                "routes": route_results,
                "issues": [],
            }
        return {
            "schema_version": BROWSER_AUDIT_SCHEMA_VERSION,
            "script_version": BROWSER_AUDIT_SCRIPT_VERSION,
            "run_id": self.run_id,
            "pack_hash": freeze.pack_hash,
            "ui_bundle_hash": freeze.ui_bundle_hash,
            "browser_input_hash": freeze.browser_input_hash,
            "ui_file_count": freeze.ui_file_count,
            "routes": routes,
            "viewports": viewports,
            "issues": [],
            "verdict": "GREEN",
        }

    def _record_current_reviews(self) -> None:
        stages = ("evidence", "science", "calculation", "writing", "browser", "final")
        for round_no, stage in enumerate(stages, start=1):
            record_agent_review(
                self.conn,
                self.run_id,
                round_no,
                f"{stage}_reviewer",
                "GREEN",
                "resolved",
                "[]",
                review_stage=stage,
                reviewer_id=f"test-{stage}",
                review_kind="deterministic" if stage == "browser" else "independent",
                input_artifact_hash=(
                    self.freeze.browser_input_hash if stage == "browser" else self.freeze.pack_hash
                ),
                output_artifact_hash=(
                    self.browser_manifest_hash if stage == "browser" else sha256_text(f"{stage}-output")
                ),
            )

    def test_current_pack_and_ui_bound_reviews_are_eligible(self) -> None:
        report = evaluate_publication_gate(self.conn, self.run_id, project_root=self.root)
        self.assertTrue(report.eligible, report.blockers)
        self.assertTrue(report.details["strict_artifact_binding"])
        self.assertTrue(report.details["browser_visual_audit"]["valid"])

    def test_bound_run_can_be_published_from_temporary_database(self) -> None:
        report = publish_run(
            self.conn,
            self.run_id,
            reason="temporary test publication",
            project_root=self.root,
        )
        self.assertTrue(report.eligible)
        row = self.conn.execute(
            "SELECT run_status,run_readiness_status FROM opportunity_run WHERE id=?",
            (self.run_id,),
        ).fetchone()
        self.assertEqual((row["run_status"], row["run_readiness_status"]), ("completed", "published"))

    def test_replacing_pack_immediately_invalidates_old_green_reviews(self) -> None:
        self._insert_pack_manifest(b'{"pack":"v2"}')
        report = evaluate_publication_gate(self.conn, self.run_id, project_root=self.root)
        self.assertFalse(report.eligible)
        self.assertTrue(any("reviewer 已过期" in item and "evidence" in item for item in report.blockers))
        self.assertTrue(any("browser audit pack_hash 已过期" in item for item in report.blockers))

    def test_viewer_change_invalidates_browser_review_and_audit_only(self) -> None:
        css = self.root / "tools" / "viewer" / "static" / "opportunity_lens.css"
        css.write_text(css.read_text(encoding="utf-8") + ".changed { color: red; }\n", encoding="utf-8")
        report = evaluate_publication_gate(self.conn, self.run_id, project_root=self.root)
        self.assertFalse(report.eligible)
        self.assertTrue(any("reviewer 已过期" in item and "browser" in item for item in report.blockers))
        self.assertFalse(any("reviewer 已过期" in item and "evidence" in item for item in report.blockers))
        self.assertTrue(any("ui_bundle_hash 已过期" in item for item in report.blockers))

    def test_read_model_change_invalidates_browser_review_and_audit_only(self) -> None:
        read_models = self.root / "tools" / "opportunity_lens" / "read_models.py"
        read_models.write_text(
            read_models.read_text(encoding="utf-8") + "DISPLAY_VERSION = 2\n",
            encoding="utf-8",
        )
        report = evaluate_publication_gate(self.conn, self.run_id, project_root=self.root)
        self.assertFalse(report.eligible)
        self.assertTrue(any("reviewer 已过期" in item and "browser" in item for item in report.blockers))
        self.assertFalse(any("reviewer 已过期" in item and "evidence" in item for item in report.blockers))
        self.assertTrue(any("ui_bundle_hash 已过期" in item for item in report.blockers))

    def test_missing_per_table_geometry_and_screenshot_hash_block_publication(self) -> None:
        malformed = json.loads(json.dumps(self.browser_manifest))
        malformed_table = malformed["viewports"]["desktop"]["routes"][0]["tables"][0]
        malformed_table.pop("rightmost_column")
        malformed_table.pop("right_edge_screenshot_hash")
        malformed["viewports"]["mobile"]["routes"][0].pop("screenshot_hash")
        malformed_hash = browser_audit_manifest_hash(malformed)
        self.conn.execute(
            """
            INSERT INTO opportunity_run_manifest(
              run_id,manifest_type,manifest_json,manifest_hash,
              workflow_contract_version,pack_schema_version
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                self.run_id,
                "browser_visual_audit",
                json.dumps(malformed, ensure_ascii=False, sort_keys=True),
                malformed_hash,
                "research.workflow.v2",
                RUN_PACK_SCHEMA_VERSION,
            ),
        )
        record_agent_review(
            self.conn,
            self.run_id,
            99,
            "browser_reviewer",
            "GREEN",
            "resolved",
            "[]",
            review_stage="browser",
            reviewer_id="test-browser-malformed",
            review_kind="deterministic",
            input_artifact_hash=self.freeze.browser_input_hash,
            output_artifact_hash=malformed_hash,
        )
        report = evaluate_publication_gate(self.conn, self.run_id, project_root=self.root)
        self.assertFalse(report.eligible)
        self.assertTrue(any("rightmost_column 缺失" in item for item in report.blockers))
        self.assertTrue(any("right_edge_screenshot" in item for item in report.blockers))
        self.assertTrue(any("screenshot_hash" in item for item in report.blockers))

    def test_changed_screenshot_bytes_block_publication(self) -> None:
        screenshot_ref = self.browser_manifest["viewports"]["desktop"]["routes"][0]["screenshot_ref"]
        (self.root / screenshot_ref).write_bytes(b"tampered-screenshot")
        report = evaluate_publication_gate(self.conn, self.run_id, project_root=self.root)
        self.assertFalse(report.eligible)
        self.assertTrue(any("截图 hash 校验失败" in item for item in report.blockers))

    def test_changed_table_or_drawer_screenshot_bytes_block_publication(self) -> None:
        route = self.browser_manifest["viewports"]["desktop"]["routes"][0]
        for screenshot_ref in (
            route["tables"][0]["right_edge_screenshot_ref"],
            route["evidence_drawer"]["drawer_screenshot_ref"],
        ):
            (self.root / screenshot_ref).write_bytes(b"tampered-screenshot")
        report = evaluate_publication_gate(self.conn, self.run_id, project_root=self.root)
        self.assertFalse(report.eligible)
        self.assertTrue(any("right_edge_screenshot" in item for item in report.blockers))
        self.assertTrue(any("evidence_drawer.drawer" in item for item in report.blockers))

    def test_browser_review_output_must_match_latest_audit_manifest(self) -> None:
        newer = json.loads(json.dumps(self.browser_manifest))
        newer["finished_at"] = "2026-07-19T04:00:00+08:00"
        newer_hash = record_browser_visual_audit(
            self.conn,
            self.run_id,
            newer,
            project_root=self.root,
        )
        self.assertNotEqual(newer_hash, self.browser_manifest_hash)
        report = evaluate_publication_gate(self.conn, self.run_id, project_root=self.root)
        self.assertFalse(report.eligible)
        self.assertTrue(any("输出 hash 未绑定最新" in item for item in report.blockers))

    def test_incomplete_route_list_cannot_be_recorded(self) -> None:
        incomplete = json.loads(json.dumps(self.browser_manifest))
        missing_route = "/opportunity-lens/request-generator"
        incomplete["routes"].remove(missing_route)
        for viewport in incomplete["viewports"].values():
            viewport["routes"] = [
                item for item in viewport["routes"] if item["route"] != missing_route
            ]
            viewport["route_count"] = len(viewport["routes"])
        with self.assertRaisesRegex(ValueError, "缺少当前 run 公开路由"):
            record_browser_visual_audit(
                self.conn,
                self.run_id,
                incomplete,
                project_root=self.root,
            )

    def test_expected_routes_cover_every_stable_factor_and_slot_page(self) -> None:
        routes = expected_public_routes(self.conn, self.run_id)
        self.assertIn(f"/opportunity-lens/run/{self.run_id}/audit", routes)
        self.assertIn(f"/opportunity-lens/run/{self.run_id}/supplement", routes)
        self.assertIn(f"/opportunity-lens/run/{self.run_id}/export", routes)
        self.assertEqual(
            [route for route in routes if route.startswith("/opportunity-lens/factor/")],
            [f"/opportunity-lens/factor/{factor_id}" for factor_id in self.factor_ids],
        )
        self.assertEqual(
            [route for route in routes if route.startswith("/opportunity-lens/metric-slot/")],
            [f"/opportunity-lens/metric-slot/{slot_id}" for slot_id in self.slot_ids],
        )

    def test_missing_factor_or_slot_route_cannot_be_recorded(self) -> None:
        for missing_route in (
            f"/opportunity-lens/factor/{self.factor_ids[-1]}",
            f"/opportunity-lens/metric-slot/{self.slot_ids[-1]}",
        ):
            incomplete = json.loads(json.dumps(self.browser_manifest))
            incomplete["routes"].remove(missing_route)
            for viewport in incomplete["viewports"].values():
                viewport["routes"] = [
                    item for item in viewport["routes"] if item["route"] != missing_route
                ]
                viewport["route_count"] = len(viewport["routes"])
            with self.assertRaisesRegex(ValueError, "缺少当前 run 公开路由"):
                record_browser_visual_audit(
                    self.conn,
                    self.run_id,
                    incomplete,
                    project_root=self.root,
                )

    def test_internal_route_cannot_be_smuggled_into_public_browser_audit(self) -> None:
        unexpected = json.loads(json.dumps(self.browser_manifest))
        internal_route = f"/api/opportunity-lens/run/{self.run_id}"
        unexpected["routes"].append(internal_route)
        for viewport in unexpected["viewports"].values():
            cloned = json.loads(json.dumps(viewport["routes"][0]))
            cloned["route"] = internal_route
            viewport["routes"].append(cloned)
            viewport["route_count"] = len(viewport["routes"])
        validation = validate_browser_visual_audit(
            unexpected,
            expected_freeze=self.freeze,
            project_root=self.root,
            verify_screenshots=True,
            expected_routes=expected_public_routes(self.conn, self.run_id),
        )
        self.assertFalse(validation.valid)
        self.assertTrue(
            any("包含非公开或非当前 run 路由" in issue for issue in validation.issues)
        )

    def test_missing_or_machine_facing_evidence_drawer_blocks_audit(self) -> None:
        missing = json.loads(json.dumps(self.browser_manifest))
        missing["viewports"]["desktop"]["routes"][0].pop("evidence_drawer")
        validation = validate_browser_visual_audit(
            missing,
            expected_freeze=self.freeze,
            project_root=self.root,
            verify_screenshots=True,
            expected_routes=expected_public_routes(self.conn, self.run_id),
        )
        self.assertFalse(validation.valid)
        self.assertTrue(any("缺少证据抽屉审计" in issue for issue in validation.issues))

        machine_facing = json.loads(json.dumps(self.browser_manifest))
        drawer_item = machine_facing["viewports"]["desktop"]["routes"][0][
            "evidence_drawer"
        ]["items"][0]
        drawer_item["forbidden_fragments"] = ["source_ref"]
        drawer_item["raw_machine_date_fragments"] = ["2026-05-07"]
        drawer_item["raw_source_level_code_fragments"] = ["A"]
        drawer_item["raw_json_visible"] = True
        drawer_item["source_ref"] = "opp://source/secret"
        validation = validate_browser_visual_audit(
            machine_facing,
            expected_freeze=self.freeze,
            project_root=self.root,
            verify_screenshots=True,
            expected_routes=expected_public_routes(self.conn, self.run_id),
        )
        self.assertFalse(validation.valid)
        self.assertTrue(any("forbidden_fragments 非空" in issue for issue in validation.issues))
        self.assertTrue(any("raw_machine_date_fragments 非空" in issue for issue in validation.issues))
        self.assertTrue(any("raw_source_level_code_fragments 非空" in issue for issue in validation.issues))
        self.assertTrue(any("raw_json_visible 必须为 false" in issue for issue in validation.issues))
        self.assertTrue(any("不得保存原始引用" in issue for issue in validation.issues))

    def test_evidence_date_audit_preserves_iso_dates_inside_quoted_excerpts(self) -> None:
        human_date_fields = [
            {"label": "发布日期", "value": "2026年5月7日"},
            {"label": "事件/版本日期", "value": "2026年春季招聘周期"},
        ]
        excerpt_text = "引用的原文摘录：The filing was submitted on 2026-05-07."
        self.assertEqual(
            detect_raw_machine_date_fragments(human_date_fields, excerpt_text),
            [],
        )
        self.assertEqual(
            detect_raw_machine_date_fragments(
                [{"label": "发布日期", "value": "2026-05-07"}],
                excerpt_text,
            ),
            ["2026-05-07"],
        )
        self.assertEqual(
            detect_raw_machine_date_fragments(
                human_date_fields,
                excerpt_text + " current_at_fetch",
            ),
            ["current_at_fetch"],
        )

    def test_embedded_red_issues_are_reported_without_quadruplicate_noise(self) -> None:
        red = json.loads(json.dumps(self.browser_manifest))
        red["verdict"] = "RED"
        red["issues"] = [{"viewport": "desktop", "route": red["routes"][0]}]
        route = red["viewports"]["desktop"]["routes"][0]
        route["issues"] = ["table 0: right edge not reached"]
        table = route["tables"][0]
        table["issues"] = ["right edge not reached"]
        table["right_edge"]["scroll_left"] = 0.0
        table["right_edge"]["max_scroll_left"] = 20.0
        table["right_edge"]["reached"] = False
        validation = validate_browser_visual_audit(
            red,
            expected_freeze=self.freeze,
            project_root=self.root,
            verify_screenshots=True,
            expected_routes=expected_public_routes(self.conn, self.run_id),
        )
        self.assertFalse(validation.valid)
        self.assertEqual(
            len([issue for issue in validation.issues if "right_edge" in issue]),
            1,
            validation.issues,
        )
        self.assertFalse(any("tables[0].issues" in issue for issue in validation.issues))

    def test_blank_rightmost_header_remains_a_contract_failure(self) -> None:
        blank_header = json.loads(json.dumps(self.browser_manifest))
        blank_header["viewports"]["desktop"]["routes"][0]["tables"][0][
            "rightmost_column"
        ]["header_text"] = ""
        validation = validate_browser_visual_audit(
            blank_header,
            expected_freeze=self.freeze,
            project_root=self.root,
            verify_screenshots=True,
            expected_routes=expected_public_routes(self.conn, self.run_id),
        )
        self.assertFalse(validation.valid)
        self.assertTrue(any("header_text 为空" in issue for issue in validation.issues))

    def test_historical_published_run_is_not_retroactively_revalidated(self) -> None:
        self.conn.execute(
            "UPDATE opportunity_run SET run_status='completed',run_readiness_status='published' WHERE id=?",
            (self.run_id,),
        )
        self.conn.execute(
            "DELETE FROM opportunity_run_manifest WHERE run_id=? AND manifest_type='browser_visual_audit'",
            (self.run_id,),
        )
        report = evaluate_publication_gate(self.conn, self.run_id, project_root=self.root)
        self.assertFalse(report.eligible)
        self.assertFalse(report.details["strict_artifact_binding"])
        self.assertFalse(any("browser visual audit" in item for item in report.blockers))
        self.assertTrue(any("run_status 必须是 under_review" in item for item in report.blockers))


if __name__ == "__main__":
    unittest.main()
