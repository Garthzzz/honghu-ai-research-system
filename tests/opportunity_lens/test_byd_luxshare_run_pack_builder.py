from __future__ import annotations

import unittest

from tools.opportunity_lens.build_byd_luxshare_optical_competition_run_pack import (
    BYD_EVIDENCE_PATH,
    FINANCIAL_PATH,
    INDUSTRY_EVIDENCE_PATH,
    LUX_EVIDENCE_PATH,
    MARKET_ENTITY_SPECS,
    _CLAIM_EXCERPT_OVERRIDES,
    THEORY_ANSWER_DETAILS,
    THEORY_ANSWER_REFS,
    THEORY_CONCLUSION_DETAILS,
    THEORY_ENTITY_SPECS,
    THEORY_LITERATURE_REFS,
    THEORY_METHOD_DETAILS,
    THEORY_METHOD_REFS,
    TARGET_PARENT_RESEARCH_RELATIONS,
    _CLAIM_SUBJECT_OVERRIDES,
    _company_region_probability_rows,
    _enrich_source_excerpts_from_evidence,
    _financial_status_for_target,
    _geography_joint_probability_rows,
    _joint_scope_probability_rows,
    _load_json,
    _luxshare_conflict_sources,
    _model_config,
    _normalize_claim,
    _normalize_data_point,
    _normalize_source,
    _normalized_risk_score,
    _policy_role_for_source,
    _round_half_up,
    _public_source_class,
    _source_hosting_channel,
    _source_provenance,
    _wilson_interval,
)
from tools.opportunity_lens.byd_luxshare_competition_model import (
    _validate_prior_update_bridge,
)


class BydLuxshareRunPackBuilderGuardrailTests(unittest.TestCase):
    def test_luxshare_regulatory_conflict_sources_have_exact_pdf_locators(self):
        sources = {row["ref"]: row for row in _luxshare_conflict_sources()}
        expected = {
            "LX-ANNUAL-2024": ("PDF第16页", "顺利通过头部AI智算中心客户的测试验证"),
            "LX-IR-20260507": ("PDF第5页", "光连接方面，我们才起步"),
            "LX-IR-20260525": ("PDF第2页", "暂不具备自研1.6T硅光芯片的能力"),
        }
        for ref, (locator, excerpt) in expected.items():
            self.assertIn(locator, sources[ref]["local_locator"])
            self.assertIn(excerpt, sources[ref]["excerpt"])
        self.assertIn("第6页Q32", sources["LX-IR-20260507"]["local_locator"])

    def test_corrected_primary_excerpts_keep_subject_date_and_scope_explicit(self):
        byd = _load_json(BYD_EVIDENCE_PATH)
        byd_sources = {row["ref"]: row for row in byd["sources"]}
        self.assertIn("比亚迪电子（国际）有限公司｜香港", byd_sources["BYD-S02"]["excerpt"])
        self.assertIn("间接持股65.76", byd_sources["BYD-S02"]["excerpt"])
        self.assertIn("（73）专利权人 济南比亚迪半导体技术有限公司", byd_sources["BYD-S11"]["excerpt"])
        self.assertEqual(byd_sources["BYD-S11"]["language"], "zh")

        lux = _load_json(LUX_EVIDENCE_PATH)
        lux_sources = {row["ref"]: row for row in lux["sources"]}
        self.assertIn("have become our most shipped products", lux_sources["LX-FRO-2026"]["excerpt"])
        self.assertIn("bulk shipments progressing steadily", lux_sources["LX-FRO-2026"]["excerpt"])
        fro_points = [row for row in lux["data_points"] if row["source_ref"] == "LX-FRO-2026"]
        self.assertFalse(any("issuer_stage_2026_05" in row["scope_key"] for row in fro_points))

        industry = _load_json(INDUSTRY_EVIDENCE_PATH)
        industry_sources = {row["ref"]: row for row in industry["sources"]}
        cignal = industry_sources["SRC-CIGNAL-4Q24"]
        self.assertEqual(cignal["publish_date"], "2025-05-07")
        self.assertIn("under 1M units", cignal["excerpt"])
        self.assertIn("no material impact to pluggable shipments", cignal["excerpt"])
        cignal_points = [row for row in industry["data_points"] if row["source_ref"] == "SRC-CIGNAL-4Q24"]
        self.assertEqual({row["as_of_date"] for row in cignal_points}, {"2025-05-07"})

    def test_group_level_claims_do_not_inherit_a_single_byd_legal_entity(self):
        for claim_id in ("BYD-C04", "BYD-C05", "BYD-C06"):
            subject = _CLAIM_SUBJECT_OVERRIDES[claim_id]
            self.assertIsNone(subject["legal_entity_key"])
            self.assertEqual(subject["control_group_key"], "controlled_group:byd")
            self.assertNotEqual(subject["legal_entity_status"], "mapped")

    def test_luxshare_tech_product_pages_are_issuer_controlled(self):
        tier, origin = _public_source_class(
            {
                "ref": "LX-TRANSCEIVER-CURRENT",
                "publisher": "Luxshare-Tech",
                "title": "Optical Transceivers",
                "source_tier": "C",
            }
        )
        self.assertEqual(tier, "Tier 1")
        self.assertEqual(origin, "issuer_controlled")
        provenance = _source_provenance(
            {
                "ref": "LX-TRANSCEIVER-CURRENT",
                "publisher": "Luxshare-Tech",
                "source_tier": "C",
                "source_review_status": "weak_source_only",
                "independence_key": "luxshare_group_controlled",
            }
        )
        self.assertEqual(provenance["source_tier"], "B")
        self.assertEqual(provenance["source_review_status"], "pass_with_note")
        self.assertEqual(provenance["corroboration_key"], "controlled_group:luxshare")
        self.assertEqual(
            _policy_role_for_source({**provenance, "ref": "LX-TRANSCEIVER-CURRENT"}),
            "core_evidence",
        )

    def test_source_without_real_locator_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "缺少可核验的 url/local_path"):
            _normalize_source(
                {
                    "ref": "MISSING-LOCATOR",
                    "title": "仅供测试",
                    "publisher": "test",
                    "excerpt": "没有真实 URL 或本地文件。",
                }
            )

    def test_old_engineering_records_used_for_current_judgment_warn_readers(self):
        for ref in (
            "POET-LX-202408",
            "OIF-OFC2024-CEI",
            "KEYSIGHT-LX-202410",
        ):
            source = _normalize_source(
                {
                    "ref": ref,
                    "title": "2024年工程活动记录",
                    "publisher": "测试发布方",
                    "publish_date": "2024-10-01",
                    "url": f"https://example.com/{ref}",
                    "excerpt": "该记录用于确认当时的工程活动。",
                }
            )
            self.assertIn("严重时效提醒", source["freshness_warning"])
            self.assertIn("不能单独证明截至2026年", source["freshness_warning"])

    def test_inferred_point_records_formula_inputs_and_scope(self):
        point = _normalize_data_point(
            {
                "source_ref": "MODEL-INPUTS",
                "entity_key": "sample:historical_optical_entry_cases",
                "metric": "示例推导值",
                "period": "2026",
                "value_num": 1.5,
                "unit": "倍",
                "scope_key": "demo",
                "source_excerpt": "原始输入为3和2。",
                "extraction_method": "inferred",
                "calculation": "3 / 2 = 1.5",
            }
        )
        self.assertIn("公式/算法：", point["note"])
        self.assertIn("输入：", point["note"])
        self.assertIn("口径：", point["note"])
        self.assertIn("scope_key=sample:historical_optical_entry_cases|demo", point["note"])

    def test_historical_base_rates_share_one_reproducible_nine_case_ledger(self):
        evidence = _load_json(INDUSTRY_EVIDENCE_PATH)
        raw_points = {
            point["data_point_id"]: point for point in evidence["data_points"]
        }
        strict_point = _normalize_data_point(raw_points["DP-I-081"])
        broad_point = _normalize_data_point(raw_points["DP-I-082"])
        strict_ledger = strict_point["observations"]
        broad_ledger = broad_point["observations"]
        self.assertEqual(len(strict_ledger), 9)
        self.assertEqual(
            [row["case_id"] for row in strict_ledger],
            [row["case_id"] for row in broad_ledger],
        )
        self.assertEqual(
            sum(row["strict_full_stack_success"] for row in strict_ledger), 2
        )
        self.assertEqual(
            sum(row["broad_adjacency_success"] for row in strict_ledger), 5
        )
        for row in strict_ledger:
            self.assertTrue(row["source_refs"])
            self.assertTrue(row["entry_path"])
            self.assertTrue(row["outcome_as_of"])
            self.assertTrue(row["classification_rationale"])
        self.assertEqual(strict_point["value_num"], 22.22)
        self.assertEqual(broad_point["value_num"], 55.56)
        self.assertIn("center=(p+z²/(2n))", strict_point["note"])

        config = _model_config(_load_json(FINANCIAL_PATH))
        bridge = config["probability"]["prior_update_bridge"]
        _validate_prior_update_bridge(config["probability"])
        self.assertEqual(
            bridge["historical_anchors"]["complete_module_success"][
                "wilson_95_interval"
            ],
            _wilson_interval(2, 9),
        )
        all_case_refs = []
        for row in bridge["historical_case_ledger"]:
            for ref in row["source_refs"]:
                if ref not in all_case_refs:
                    all_case_refs.append(ref)
        self.assertEqual(
            bridge["historical_anchors"]["adjacent_or_complete_success"][
                "source_refs"
            ],
            all_case_refs,
        )

    def test_historical_base_rate_validation_fails_if_case_flag_is_mutated(self):
        config = _model_config(_load_json(FINANCIAL_PATH))
        config["probability"]["prior_update_bridge"]["historical_case_ledger"][0][
            "strict_full_stack_success"
        ] = 0
        with self.assertRaisesRegex(ValueError, "successes 无法从案例账本复算"):
            _validate_prior_update_bridge(config["probability"])

    def test_financial_exposure_upper_bound_is_an_explicit_frozen_input(self):
        config = _model_config(_load_json(FINANCIAL_PATH))
        for company_key in ("innolight", "eoptolink"):
            self.assertIn(
                "high_speed_revenue_exposure_share",
                config["financial"]["companies"][company_key],
            )
            self.assertEqual(
                config["financial"]["companies"][company_key][
                    "high_speed_revenue_exposure_share"
                ],
                1.0,
            )
        registry = config["financial"]["parameter_registry"]
        exposure = next(
            row
            for row in registry
            if row["parameter_path"].endswith(
                "high_speed_revenue_exposure_share"
            )
        )
        self.assertIn("压力上限", exposure["formula_or_method"])
        self.assertIn("中心预测", exposure["update_rule"])

    def test_crealights_source_keeps_english_original_translation_and_locator(self):
        source = _normalize_source(
            {
                "ref": "SRC-HKEX-ASP26",
                "title": "old generic title",
                "publisher": "HKEX / listing applicant",
                "publish_date": "2026-06-11",
                "url": "https://invalid.example/old.pdf",
                "tier": "T1_regulatory_filing_company_specific",
                "language": "zh",
                "excerpt": "平均售价下降",
                "independence_key": "legacy",
            }
        )
        self.assertEqual(source["language"], "en")
        self.assertIn("Crealights Technology", source["title"])
        self.assertIn("北京海光芯正", source["title_zh"])
        self.assertIn("PDF P143", source["local_locator"])
        self.assertIn("RMB2,443", source["excerpt"])
        self.assertIn("2,443", source["excerpt_zh"])
        self.assertEqual(source["issuer_key"], "issuer:crealights")

    def test_theory_profiles_have_distinct_method_and_decision_boundaries(self):
        expected = set(THEORY_ENTITY_SPECS)
        self.assertEqual(set(THEORY_METHOD_DETAILS), expected)
        self.assertEqual(set(THEORY_ANSWER_DETAILS), expected)
        self.assertEqual(set(THEORY_CONCLUSION_DETAILS), expected)
        self.assertEqual(len(set(THEORY_METHOD_DETAILS.values())), len(expected))
        self.assertEqual(len(set(THEORY_ANSWER_DETAILS.values())), len(expected))
        self.assertEqual(len(set(THEORY_CONCLUSION_DETAILS.values())), len(expected))
        for key in expected:
            self.assertGreater(len(THEORY_METHOD_DETAILS[key]), 100)
            self.assertGreater(len(THEORY_ANSWER_DETAILS[key]), 40)
            self.assertGreater(len(THEORY_CONCLUSION_DETAILS[key]), 40)

    def test_theory_prose_citation_registry_covers_every_profile(self):
        expected = set(THEORY_ENTITY_SPECS)
        self.assertEqual(set(THEORY_LITERATURE_REFS), expected)
        self.assertEqual(set(THEORY_METHOD_REFS), expected)
        self.assertEqual(set(THEORY_ANSWER_REFS), expected)
        for key in expected:
            self.assertTrue(THEORY_LITERATURE_REFS[key])
            self.assertTrue(THEORY_METHOD_REFS[key])
            self.assertTrue(THEORY_ANSWER_REFS[key])
        self.assertIn(
            "MODEL-WORKPAPER",
            THEORY_METHOD_REFS["probability_method_and_baserate"],
        )
        self.assertIn(
            "NVIDIA-CX8-VALIDATED",
            THEORY_ANSWER_REFS["qualification_upstream_constraints"],
        )
        self.assertTrue(
            {"BYD-S01", "BYD-S02", "BYD-S08", "BYD-S09"}.issubset(
                THEORY_ANSWER_REFS["entity_scope_and_stage_definitions"]
            )
        )
        self.assertTrue(
            {"BYD-S06", "BYD-S11", "BYD-S16", "BYD-S20"}.issubset(
                THEORY_ANSWER_REFS["recruitment_patent_capacity_audit"]
            )
        )

    def test_region_probability_contract_exposes_company_joint_and_geography_states(self):
        distribution = {"mean": 0.4, "p10": 0.2, "median": 0.35, "p90": 0.7}
        marginal = {
            key: distribution
            for key in (
                "byd_china_entry",
                "byd_global_entry",
                "luxshare_china_entry",
                "luxshare_global_entry",
                "at_least_one_entry",
                "both_entry",
                "at_least_one_china_entry",
                "both_china_entry",
                "at_least_one_global_entry",
                "both_global_entry",
            )
        }
        geography = {
            key: distribution
            for key in (
                "china_only",
                "global_only",
                "china_and_global",
                "entry_route_unidentified",
                "no_meaningful_entry",
            )
        }
        model = {
            "probability": {
                "horizons": {
                    horizon: {
                        "marginal_probability_summary": marginal,
                        "geography_scope_probability_summary": geography,
                    }
                    for horizon in ("3y", "5y")
                }
            }
        }
        self.assertEqual(len(_company_region_probability_rows(model)), 8)
        self.assertEqual(len(_joint_scope_probability_rows(model)), 12)
        self.assertEqual(len(_geography_joint_probability_rows(model)), 10)
        self.assertTrue(
            all(len(row) == 7 for row in _company_region_probability_rows(model))
        )

    def test_public_source_mapping_keeps_internal_artifacts_out_of_external_tiers(self):
        self.assertEqual(
            _public_source_class({"ref": "MODEL-WORKPAPER"}),
            ("Internal", "internal_model_audit"),
        )
        self.assertEqual(
            _public_source_class({"ref": "FIN-INNOLIGHT"}),
            ("Structured", "structured_financial"),
        )
        self.assertEqual(
            _public_source_class({"ref": "JOB-ZHAOPIN-COUPLING", "source_tier": "D"}),
            ("Tier 4", "weak_signal"),
        )
        self.assertEqual(
            _public_source_class(
                {
                    "ref": "BYD-S01",
                    "publisher": "BYD Electronic (International) / HKEX",
                    "title": "Annual Report 2025",
                }
            ),
            ("Tier 1", "issuer_controlled"),
        )
        self.assertEqual(
            _source_hosting_channel(
                {
                    "ref": "BYD-S01",
                    "publisher": "BYD Electronic / HKEX",
                    "url": "https://www.hkexnews.hk/example.pdf",
                }
            ),
            "exchange_filing_archive_hkex",
        )

    def test_source_drawer_excerpt_aggregates_verified_same_record_snippets(self):
        sources = [
            {
                "ref": "BYD-S01",
                "excerpt": "一体化解决方案。",
                "excerpt_zh": "一体化解决方案。",
            }
        ]
        evidence = {
            "data_points": [
                {
                    "source_ref": "BYD-S01",
                    "extraction_method": "pdf_direct",
                    "source_excerpt": "人工智能基础设施业务收入约人民币943百万元。",
                    "source_excerpt_zh": "人工智能基础设施业务收入约人民币943百万元。",
                },
                {
                    "source_ref": "BYD-S01",
                    "extraction_method": "pdf_direct",
                    "source_excerpt": "液冷产品进入小规模试产。",
                    "source_excerpt_zh": "液冷产品进入小规模试产。",
                },
                {
                    "source_ref": "BYD-S01",
                    "metric": "ai_infrastructure_revenue",
                    "period": "FY2025",
                    "value_num": 943_000_000,
                    "unit": "CNY",
                    "extraction_method": "inferred",
                    "source_excerpt": "人工智能基础设施业务收入。",
                    "source_excerpt_zh": "人工智能基础设施业务收入。",
                },
                {
                    "source_ref": "BYD-S01",
                    "metric": "optical_line_absence_audit",
                    "period": "bounded_page_audit",
                    "extraction_method": "web_fetch",
                    "source_excerpt": "页面未列出光模块专线。",
                    "source_excerpt_zh": "页面未列出光模块专线。",
                },
            ]
        }
        _enrich_source_excerpts_from_evidence(sources, [("", evidence)])
        self.assertIn("943百万元", sources[0]["excerpt_zh"])
        self.assertIn("小规模试产", sources[0]["excerpt_zh"])
        self.assertNotIn("结构化数据点", sources[0]["excerpt_zh"])
        self.assertNotIn("页面未列", sources[0]["excerpt_zh"])

    def test_target_financial_status_uses_actual_available_periods(self):
        status = _financial_status_for_target(
            "byd_electronic",
            [
                {
                    "source_ref": "FIN-BYD_ELECTRONIC",
                    "fact_type": "structured_financial_series",
                    "observations": [
                        {"period": "2023", "value_num": 1},
                        {"period": "2024", "value_num": 2},
                        {"period": "2025", "value_num": 3},
                    ],
                },
                {
                    "source_ref": "FIN-BYD_ELECTRONIC",
                    "fact_type": "structured_market_snapshot",
                    "as_of_date": "2026-07-17",
                    "value_num": 4,
                },
            ],
        )
        self.assertIn("2023—2025年实际财务", status)
        self.assertNotIn("2026Q1", status)
        self.assertIn("2026-07-17", status)
        self.assertIn("未披露的未来收入和现金流只在情景测算中出现", status)

    def test_target_parent_relations_are_subject_specific_human_analysis(self):
        self.assertEqual(
            set(TARGET_PARENT_RESEARCH_RELATIONS),
            {"byd_electronic", "byd", "luxshare", "innolight", "eoptolink"},
        )
        self.assertEqual(
            len(set(TARGET_PARENT_RESEARCH_RELATIONS.values())),
            len(TARGET_PARENT_RESEARCH_RELATIONS),
        )
        for company_key, text in TARGET_PARENT_RESEARCH_RELATIONS.items():
            self.assertGreater(len(text), 45, company_key)
            self.assertNotIn("破坏程度", text)

    def test_market_factor_sets_are_factor_specific_and_have_five_groups(self):
        self.assertEqual(len(MARKET_ENTITY_SPECS), 4)
        for entity_key, spec in MARKET_ENTITY_SPECS.items():
            self.assertEqual(len(spec["factors"]), 5, entity_key)
            signatures = []
            for factor in spec["factors"]:
                groups = {
                    item["corroboration_key"]
                    for item in factor["evidence"]
                    if item.get("score_eligible", True)
                }
                self.assertGreaterEqual(len(groups), 5, (entity_key, factor["factor_code"]))
                signatures.append(tuple(sorted(groups)))
            self.assertEqual(len(set(signatures)), 5, entity_key)

    def test_market_scores_and_bands_are_recomputed_with_half_up(self):
        expected = {
            "byd_entry_risk": (34, 20, 51, 33.60),
            "luxshare_entry_risk": (61, 48, 73, 60.50),
            "innolight_terminal_risk": (53, 35, 70, 52.95),
            "eoptolink_terminal_risk": (57, 38, 74, 56.60),
        }
        for entity_key, spec in MARKET_ENTITY_SPECS.items():
            self.assertAlmostEqual(sum(spec["weights"].values()), 1.0)
            base = low = high = 0.0
            for factor in spec["factors"]:
                weight = spec["weights"][factor["factor_code"]]
                normalized = _normalized_risk_score(
                    factor["score_raw_construct"], factor["score_orientation"]
                )
                base += weight * normalized
                low += weight * factor["score_low_normalized_risk"]
                high += weight * factor["score_high_normalized_risk"]
            point, band_low, band_high, unrounded = expected[entity_key]
            self.assertAlmostEqual(base, unrounded, places=8)
            self.assertEqual(_round_half_up(base), point)
            self.assertEqual(_round_half_up(low), band_low)
            self.assertEqual(_round_half_up(high), band_high)
        self.assertEqual(_round_half_up(60.5), 61)

    def test_source_provenance_separates_record_from_control_group(self):
        base = {
            "source_tier": "S",
            "source_review_status": "pass",
            "publisher": "fixture",
            "independence_key": "legacy-record-key",
        }
        byd_annual = _source_provenance({**base, "ref": "BYD-S01"})
        byd_catalogue = _source_provenance({**base, "ref": "BYD-S04"})
        self.assertNotEqual(byd_annual["record_key"], byd_catalogue["record_key"])
        self.assertEqual(byd_annual["corroboration_key"], "controlled_group:byd")
        self.assertEqual(byd_catalogue["corroboration_key"], "controlled_group:byd")

        lux_en = _source_provenance({**base, "ref": "LX-HKEX-PROSPECTUS-EN-2026"})
        lux_zh = _source_provenance({**base, "ref": "LX-HKEX-PROSPECTUS-ZH-2026"})
        self.assertNotEqual(lux_en["record_key"], lux_zh["record_key"])
        self.assertEqual(lux_en["record_family_key"], lux_zh["record_family_key"])
        self.assertEqual(lux_en["corroboration_key"], "controlled_group:luxshare")

        yfinance = _source_provenance({**base, "ref": "FIN-BYD_ELECTRONIC"})
        self.assertEqual(yfinance["source_tier"], "B")
        self.assertEqual(yfinance["source_review_status"], "pass_with_note")
        self.assertEqual(yfinance["source_origin_class"], "structured_financial_mirror_yfinance")
        analyst = _source_provenance(
            {**base, "ref": "FIN-INNOLIGHT-ANALYST"}
        )
        self.assertEqual(analyst["issuer_key"], "structured-analyst:yfinance")
        self.assertEqual(
            analyst["corroboration_key"], "structured-analyst:yfinance"
        )
        self.assertEqual(
            analyst["source_origin_class"],
            "structured_analyst_mirror_yfinance",
        )

    def test_luxshare_claim_compiles_canonical_ledger_without_fake_counts(self):
        def source(ref: str) -> dict:
            return {
                "ref": ref,
                "publisher": "fixture",
                "source_tier": "S",
                "source_review_status": "pass",
                "independence_key": f"legacy:{ref}",
                "excerpt": f"{ref} excerpt",
                "excerpt_zh": f"{ref} 摘录",
                "publish_date": "2026-01-01",
                "event_date": "2026-01-01",
            }

        lookup = {
            ref: source(ref)
            for ref in ("LX-IR-202508", "LX-FRO-2026", "NVIDIA-CX8-VALIDATED")
        }
        claim = _normalize_claim(
            {
                "claim_id": "LX-C006",
                "claim": "监管记录称立讯1.6T处于客户验证，未署期官网页另称早期商业化；两者不能证明阶段跃迁，也未完成头部客户闭环。",
                "classification": "issuer_claim_under_validation",
                "milestone_stage": "parallel_issuer_stage_claims_without_dated_transition",
                "support_refs": ["LX-IR-202508", "LX-FRO-2026"],
                "counter_refs": ["NVIDIA-CX8-VALIDATED"],
                "confidence": "medium",
                "next_evidence_action": "取得客户侧资格或重复订单。",
            },
            lookup,
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim["supporting_source_refs"], ["LX-IR-202508", "LX-FRO-2026"])
        self.assertEqual(claim["counter_source_refs"], ["NVIDIA-CX8-VALIDATED"])
        self.assertEqual(claim["counts"]["record_count"], 3)
        self.assertEqual(claim["counts"]["independent_group_count"], 2)
        self.assertEqual(claim["factor_mapping_status"], "mapped")
        self.assertEqual(claim["next_evidence_action_status"], "provided")
        self.assertTrue(claim["source_audit"])

    def test_missing_claim_next_action_is_compiled_to_specific_supplement(self):
        source = {
            "ref": "SRC-LC-MAR26",
            "publisher": "LightCounting",
            "source_tier": "B",
            "source_review_status": "pass_with_note",
            "independence_key": "forecaster:lightcounting",
            "excerpt": "800G与1.6T预测更新。",
            "excerpt_zh": "800G与1.6T预测更新。",
            "publish_date": "2026-03-01",
            "event_date": "2026-03-01",
        }
        claim = _normalize_claim(
            {
                "claim_id": "CLM-I-001",
                "statement": "2026年800G与1.6T并存。",
                "supporting_source_refs": ["SRC-LC-MAR26"],
                "confidence": "medium_high",
            },
            {"SRC-LC-MAR26": source},
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(
            claim["next_evidence_action_status"], "research_plan_defined"
        )
        self.assertEqual(
            claim["next_evidence_action_ref"], "SUP-MARKET-ARCHITECTURE"
        )
        self.assertIn("同规格成交价", claim["next_evidence_action"])

    def test_public_claim_excerpt_uses_claim_specific_original_rows(self):
        source = {
            "ref": "SRC-INNO-AR25",
            "publisher": "中际旭创",
            "source_tier": "S",
            "source_review_status": "pass",
            "independence_key": "controlled_group:innolight",
            "excerpt": "原表字段结构化抄录：这是故意很长的来源级完整摘录。",
            "excerpt_zh": "原表字段结构化抄录：这是故意很长的来源级完整摘录。",
            "publish_date": "2026-04-23",
            "event_date": "2025-12-31",
        }
        claim = _normalize_claim(
            {
                "claim_id": "CLM-I-009",
                "statement": "两家龙头2025年均有正的简单FCF。",
                "supporting_source_refs": ["SRC-INNO-AR25"],
            },
            {"SRC-INNO-AR25": source},
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertNotIn("原表字段结构化抄录", claim["source_excerpt"])
        self.assertIn("10,896,126,160.03", claim["source_excerpt"])
        self.assertIn("2,759,994,695.91", claim["source_excerpt"])
        self.assertLess(len(claim["source_excerpt"]), 300)

    def test_byd_and_asp_claim_drawers_do_not_reuse_full_source_digest(self):
        claim_ids = [
            "BYD-C01",
            "BYD-C02",
            "BYD-C03",
            "BYD-C08",
            "BYD-C09",
            "BYD-C10",
            "BYD-C11",
            "BYD-C12",
        ]
        excerpts = [
            _CLAIM_EXCERPT_OVERRIDES[claim_id]["source_excerpt"]
            for claim_id in claim_ids
        ]
        self.assertEqual(len(set(excerpts)), len(claim_ids))
        self.assertTrue(all(len(excerpt) < 400 for excerpt in excerpts))
        self.assertLess(
            len(_CLAIM_EXCERPT_OVERRIDES["CLM-I-005"]["source_excerpt"]),
            400,
        )


if __name__ == "__main__":
    unittest.main()
