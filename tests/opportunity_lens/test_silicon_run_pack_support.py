from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tools.opportunity_lens.silicon_run_pack_support import (
    SEGMENT_FACTOR_CODES,
    apply_data_point_evidence_audit,
    apply_financial_evidence_audit,
    apply_source_catalog_corrections,
    build_financial_data_points,
    build_segment_entity,
    extract_primary_research_question,
    line_chart_panel,
    natural_citations,
    normalize_agent_data_points,
    normalize_agent_source,
    normalize_deprecated_public_headings,
    parallel_search_plan,
)


def _sources() -> dict[str, dict]:
    return {
        f"official-{index}": {
            "ref": f"official-{index}",
            "title": f"Official source {index}",
            "title_zh": f"官方来源{index}",
            "language": "en",
            "excerpt": f"Official source {index} discloses a distinct operating fact.",
            "excerpt_zh": f"官方来源{index}披露了一项彼此独立的经营事实。",
            "independence_key": f"official-group-{index}",
        }
        for index in range(1, 6)
    }


def _specification() -> dict:
    refs = list(_sources())
    factor_inputs = {}
    for index, code in enumerate(SEGMENT_FACTOR_CODES, start=1):
        factor_inputs[code] = {
            "score_raw": 50 + index,
            "coverage": 0.82,
            "confidence": 0.78,
            "score_rationale": f"因子{index}由五个独立官方来源共同约束，正面信号与执行风险同时进入评分。",
            "factor_value_summary": f"因子{index}的当前证据显示方向明确，但兑现节奏仍受到项目爬坡和客户验证约束。",
            "source_context_summary": f"因子{index}采用五个不同发布主体的原始资料，没有把转载或同一公告拆成多个来源。",
            "factor_topic_analysis": f"因子{index}提高了研究优先级，但如果后续产能、订单或现金流没有兑现，分数应当下调。",
            "theme_analysis_points": [
                f"因子{index}的多源证据方向一致。",
                f"因子{index}仍需用后续经营结果复核。",
            ],
            "source_refs": refs,
        }
    return {
        "key": "test-segment",
        "canonical_name": "测试硅片环节",
        "display_name": "测试硅片环节",
        "description": "用于验证十因子实体构建、证据独立性和综合分计算。",
        "factor_inputs": factor_inputs,
    }


def test_build_segment_entity_requires_and_builds_all_ten_factors() -> None:
    entity = build_segment_entity(
        _specification(),
        sources_by_ref=_sources(),
        as_of_date="2026-07-20",
    )
    assert len(entity["factor_scores"]) == 10
    assert {row["factor_code"] for row in entity["factor_scores"]} == set(SEGMENT_FACTOR_CODES)
    assert 50 <= entity["score_point"] <= 61
    assert entity["score_band_low"] <= entity["score_point"] <= entity["score_band_high"]
    assert entity["independent_source_count"] == 5
    assert all(len(row["information_points"]) == 5 for row in entity["factor_scores"])


def test_factor_information_points_keep_original_and_translation_layers() -> None:
    sources = _sources()
    entity = build_segment_entity(
        _specification(),
        sources_by_ref=sources,
        as_of_date="2026-07-20",
    )
    english = entity["factor_scores"][0]["information_points"][0]
    assert english["excerpt"] == sources["official-1"]["excerpt"]
    assert english["excerpt_zh"] == sources["official-1"]["excerpt_zh"]

    sources["official-1"].update({
        "language": "zh-CN",
        "excerpt": "官方来源一披露了一项可定位的经营事实。",
        "excerpt_zh": "官方来源一披露了一项可定位的经营事实。",
    })
    entity = build_segment_entity(
        _specification(),
        sources_by_ref=sources,
        as_of_date="2026-07-20",
    )
    chinese = entity["factor_scores"][0]["information_points"][0]
    assert chinese["excerpt"] == sources["official-1"]["excerpt"]
    assert "excerpt_zh" not in chinese


def test_factor_information_points_accept_factor_specific_source_excerpt() -> None:
    sources = _sources()
    specification = _specification()
    factor = specification["factor_inputs"][SEGMENT_FACTOR_CODES[0]]
    factor["evidence_information_points"] = {
        "official-1": {
            "excerpt": "The 7nm-and-below capacity rises from 850,000 to 1.4 million wafers per month.",
            "excerpt_zh": "7纳米及以下月产能由85万片增至140万片。",
        }
    }

    entity = build_segment_entity(
        specification,
        sources_by_ref=sources,
        as_of_date="2026-07-20",
    )

    point = entity["factor_scores"][0]["information_points"][0]
    assert point["excerpt"].startswith("The 7nm-and-below capacity")
    assert point["excerpt_zh"] == "7纳米及以下月产能由85万片增至140万片。"


def test_factor_information_points_reject_unbound_override_source() -> None:
    specification = _specification()
    factor = specification["factor_inputs"][SEGMENT_FACTOR_CODES[0]]
    factor["evidence_information_points"] = {
        "not-bound": {"excerpt": "This source is not bound to the factor."}
    }

    with pytest.raises(ValueError, match="未绑定来源"):
        build_segment_entity(
            specification,
            sources_by_ref=_sources(),
            as_of_date="2026-07-20",
        )


def test_build_segment_entity_rejects_missing_factor() -> None:
    spec = _specification()
    spec["factor_inputs"].pop(SEGMENT_FACTOR_CODES[-1])
    with pytest.raises(ValueError, match="因子集合不完整"):
        build_segment_entity(spec, sources_by_ref=_sources(), as_of_date="2026-07-20")


def test_build_segment_entity_rejects_non_independent_evidence() -> None:
    sources = _sources()
    for source in sources.values():
        source["independence_key"] = "one-underlying-record"
    with pytest.raises(ValueError, match="5 个独立证据组"):
        build_segment_entity(_specification(), sources_by_ref=sources, as_of_date="2026-07-20")


def test_line_chart_panel_keeps_latest_period_and_axis_bounds() -> None:
    panel = line_chart_panel(
        title="硅片面积",
        unit="MSI",
        series=[
            {
                "label": "基准",
                "observations": [
                    {"period": 2026, "value": 13_493},
                    {"period": 2027, "value": 14_653},
                    {"period": 2028, "value": 15_485},
                ],
            }
        ],
    )
    assert panel["x_start"] == "2026"
    assert panel["x_end"] == "2028"
    assert panel["series"][0]["latest_period"] == "2028"
    assert panel["series"][0]["svg_points"].startswith("0.00,")


def test_extract_primary_question_and_citation_translation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "request.md"
        path.write_text("## 必填 1：研究问题\n\n```text\n完整问题\n```\n", encoding="utf-8")
        assert extract_primary_research_question(path) == "完整问题"
    assert natural_citations("结论。[S001]") == "结论。^src:source_ref:S001"


def test_agent_source_and_parallel_series_normalization() -> None:
    source = normalize_agent_source({
        "source_id": "S001",
        "original_url_or_locator": "https://example.com/report",
        "title": "Annual report",
        "title_zh": "年度报告",
        "publisher": "Example Corp.",
        "date": "2026-04-01",
        "language": "en",
        "excerpt": "Revenue increased.",
        "excerpt_zh": "收入增长。",
        "independence_key": "issuer:example:2026",
        "independence_rationale": "发行人原始报告。",
    })
    assert source["source_tier"] == "A"
    assert source["source_channel"] == "web"
    points = normalize_agent_data_points({"data_points": [{
        "id": "DP001",
        "entity": "样本产线",
        "metric": "月产能",
        "period": "2025-2026",
        "value": None,
        "unit": "万片/月",
        "fact_type": "observed_series",
        "source_ids": ["S001"],
        "observations": [
            {"period": "2025", "value": 10},
            {"period": "2026", "value": 12},
        ],
        "note": "同一口径序列不拆成两条事实。",
    }]}, sources_by_ref={"S001": source})
    assert len(points) == 1
    assert len(points[0]["observations"]) == 2
    assert points[0]["source_excerpt_zh"] == "收入增长。"


def test_source_channel_and_first_round_parallel_search_are_explicit() -> None:
    local_source = normalize_agent_source({
        "source_id": "S002",
        "original_url_or_locator": "papers/硅片/公司年报.pdf",
        "title": "公司年报",
        "publisher": "样本公司",
        "date": "2026-04-01",
        "language": "zh",
        "excerpt": "披露月产能。",
        "independence_key": "issuer:sample:2026",
    })
    assert local_source["source_channel"] == "report"

    plan = parallel_search_plan([
        {
            "axis_key": "capacity",
            "query_text": "硅片月产能",
            "languages": ["zh", "en"],
            "status": "completed",
        }
    ])
    assert [row["source_channel"] for row in plan] == ["report", "web"]
    assert {row["axis_key"] for row in plan} == {"capacity"}


def test_deprecated_deferred_research_heading_is_not_public() -> None:
    rows = normalize_deprecated_public_headings([
        {
            "body_markdown": (
                "### 如果想进一步研究，需要补充的信息\n\n"
                "公开资料不足以判断客户认证。"
            )
        }
    ])
    assert "如果想进一步研究" not in rows[0]["body_markdown"]
    assert "### 公开证据限制" in rows[0]["body_markdown"]


def test_data_point_evidence_audit_corrects_and_drops_composite_claims() -> None:
    raw = {
        "data_points": [
            {"data_point_id": "DP001", "metric": "产能", "value": 10, "source_id": "S001", "source_excerpt": "产能10。"},
            {"data_point_id": "DP002", "metric": "收入", "value": 20, "source_id": "S002", "source_excerpt": "泛化摘要。"},
            {"data_point_id": "DP003", "metric": "复合结论", "value": 30, "source_id": "S003", "source_excerpt": "来源一。"},
        ]
    }
    audit = {
        "audits": [
            {"data_point_id": "DP001", "verdict": "pass"},
            {
                "data_point_id": "DP002",
                "verdict": "correct",
                "corrected_fields": {"value": 25},
                "corrected_excerpt": "发行人披露收入25。",
                "corrected_excerpt_zh": "发行人披露收入25。",
            },
            {
                "data_point_id": "DP003",
                "verdict": "correct",
                "corrected_excerpt": "来源一只支持一半。",
                "additional_source_ids": ["S004"],
            },
        ]
    }
    retained, summary = apply_data_point_evidence_audit(raw, audit, minimum_retained=2)
    assert [row["data_point_id"] for row in retained] == ["DP001", "DP002"]
    assert retained[1]["value"] == 25
    assert retained[1]["source_excerpt"] == "发行人披露收入25。"
    assert summary["retained_count"] == 2
    assert summary["multi_source_drop_count"] == 1


def test_data_point_evidence_audit_requires_full_coverage() -> None:
    raw = {"data_points": [{"data_point_id": "DP001", "source_excerpt": "证据。"}]}
    with pytest.raises(ValueError, match="覆盖不完整"):
        apply_data_point_evidence_audit(raw, {"audits": []}, minimum_retained=0)


def test_data_point_evidence_audit_applies_pass_excerpt_and_series_merges() -> None:
    raw = {"data_points": [
        {"data_point_id": "DP001", "subject": "样本", "metric": "收入", "period": "2024", "value": 10, "source_id": "S001", "source_excerpt": "泛化摘要。"},
        {"data_point_id": "DP002", "subject": "样本", "metric": "收入", "period": "2025", "value": 12, "source_id": "S001", "source_excerpt": "泛化摘要。"},
    ]}
    audit = {
        "data_points": [
            {"data_point_id": "DP001", "verdict": "pass", "corrected_source_excerpt": "2024年收入10。", "corrected_source_excerpt_zh": "2024年收入10。", "source_ids": ["S001"]},
            {"data_point_id": "DP002", "verdict": "pass", "corrected_source_excerpt": "2025年收入12。", "corrected_source_excerpt_zh": "2025年收入12。", "source_ids": ["S001"]},
        ],
        "required_series_merges": [{"data_point_ids": ["DP001", "DP002"]}],
    }
    retained, summary = apply_data_point_evidence_audit(raw, audit, minimum_retained=1)
    assert len(retained) == 1
    assert retained[0]["observations"] == [
        {"period": "2024", "value": 10},
        {"period": "2025", "value": 12},
    ]
    assert retained[0]["source_excerpt"] == "2024年收入10。\n2025年收入12。"
    assert summary["retained_before_series_merge"] == 2
    assert summary["series_merge_deduction"] == 1


def test_source_catalog_corrections_update_and_create_sources() -> None:
    raw = {"sources": [{"source_id": "S001", "url": "https://old.example", "title": "错误标题"}]}
    audit = {"source_corrections": [
        {
            "correction_id": "fix-s001",
            "action": "update_existing_source",
            "match": {"source_id": "S001", "url": "https://old.example"},
            "set": {"title": "正确标题", "excerpt": "精确摘录"},
        },
        {
            "correction_id": "add-s002",
            "action": "create_source_and_rebind",
            "new_source": {"source_id": "S002", "url": "https://new.example", "title": "新增来源"},
        },
    ]}
    sources, summary = apply_source_catalog_corrections(raw, audit)
    assert sources[0]["title"] == "正确标题"
    assert sources[1]["source_id"] == "S002"
    assert summary["updated_count"] == 1
    assert summary["created_count"] == 1


def test_financial_audit_applies_corrections_and_preserves_field_evidence() -> None:
    targets = {
        "targets": [
            {
                "target_id": "sample",
                "company_name_zh": "Sample",
                "ticker_verification": {
                    "official_code": "OLD",
                    "requested_market_data_alias": "OLD.DE",
                    "source_ref": "FIN-OLD",
                },
                "financials": [
                    {
                        "period": "FY2025",
                        "period_end": "2025-12-31",
                        "currency": "EUR",
                        "unit": "million",
                        "revenue": 10.0,
                        "operating_cash_flow": 2.0,
                        "source_ref": "FIN-A",
                    }
                ],
                "target_data_points": [
                    {
                        "metric_name": "old point",
                        "period": "FY2025",
                        "value_text": "old",
                        "unit": "text",
                        "evidence_ref_uri": "source_ref:FIN-OLD",
                    }
                ],
            }
        ]
    }
    sources = {
        "sources": [
            {
                "ref": "FIN-A",
                "title": "Annual report",
                "title_zh": "Annual report",
                "publisher": "Issuer",
                "url": "https://example.com/a",
                "language": "en",
                "excerpt": "generic",
                "excerpt_zh": "generic zh",
            },
            {
                "ref": "FIN-OLD",
                "title": "Old share page",
                "title_zh": "Old share page",
                "publisher": "Issuer",
                "url": "https://example.com/old",
                "language": "en",
                "excerpt": "old",
                "excerpt_zh": "old zh",
            },
        ]
    }
    audit = {
        "schema_version": "financial-audit.v1",
        "summary": {"publication_decision": "RED_until_corrections_applied"},
        "new_sources": [
            {
                "ref": "FIN-NEW",
                "title": "Share page",
                "title_zh": "Share page",
                "publisher": "Issuer",
                "url": "https://example.com/new",
                "language": "en",
                "excerpt": "ticker NEW",
                "excerpt_zh": "ticker NEW zh",
            }
        ],
        "source_corrections": [
            {
                "ref": "FIN-A",
                "action": "replace_excerpt",
                "excerpt": "revenue 11; cash flow 2",
                "excerpt_zh": "revenue 11; cash flow 2 zh",
            },
            {
                "ref": "FIN-OLD",
                "action": "supersede",
                "replacement_ref": "FIN-NEW",
            },
        ],
        "target_corrections": [
            {
                "target_id": "sample",
                "period": "ticker",
                "corrected_fields": {
                    "official_code": "NEW",
                    "requested_market_data_alias": "NEW.DE",
                    "source_ref": "FIN-NEW",
                },
                "source_ref": "FIN-NEW",
                "source_excerpt": "ticker NEW",
                "source_excerpt_zh": "ticker NEW zh",
            },
            {
                "target_id": "sample",
                "period": "FY2025",
                "corrected_fields": {"revenue": 11.0},
                "source_ref": "FIN-A",
                "source_excerpt": "revenue 11",
                "source_excerpt_zh": "revenue 11 zh",
            },
        ],
        "period_audits": [
            {
                "target_id": "sample",
                "period": "FY2025",
                "status": "correct",
                "corrected_fields": {"revenue": 11.0},
                "field_evidence": [
                    {
                        "source_ref": "FIN-A",
                        "supports": ["revenue"],
                        "source_excerpt": "revenue 11",
                        "source_excerpt_zh": "revenue 11 zh",
                    },
                    {
                        "source_ref": "FIN-NEW",
                        "supports": ["operating_cash_flow"],
                        "source_excerpt": "cash flow 2",
                        "source_excerpt_zh": "cash flow 2 zh",
                    },
                ],
            }
        ],
        "target_data_point_audits": [
            {
                "target_id": "sample",
                "status": "correct",
                "action": "replace_excerpt",
                "replacement_records": [
                    {
                        "metric_name": "new point",
                        "period": "FY2025",
                        "value_text": "11",
                        "unit": "EUR million",
                        "source_ref": "FIN-A",
                        "source_excerpt": "revenue 11",
                        "source_excerpt_zh": "revenue 11 zh",
                    }
                ],
            }
        ],
    }

    audited_targets, audited_sources, summary = apply_financial_evidence_audit(
        targets, sources, audit
    )
    target = audited_targets["targets"][0]
    assert targets["targets"][0]["ticker_verification"]["official_code"] == "OLD"
    assert target["ticker_verification"]["requested_market_data_alias"] == "NEW.DE"
    assert target["financials"][0]["revenue"] == 11.0
    assert len(target["financials"][0]["field_evidence"]) == 2
    assert target["target_data_points"][0]["source_excerpt"] == "revenue 11"
    assert summary["field_evidence_slice_count"] == 2
    assert summary["target_data_point_count"] == 1

    normalized_sources = {
        row["ref"]: normalize_agent_source(row)
        for row in audited_sources["sources"]
    }
    points = build_financial_data_points(target, normalized_sources)
    financial_points = [
        point for point in points if point["metric_category"] == "financial_history"
    ]
    assert len(financial_points) == 2
    assert financial_points[0]["value_text"] == "收入11.00"
    assert financial_points[1]["value_text"] == "经营现金流2.00"
    assert financial_points[0]["source_excerpt"] == "revenue 11"
    assert financial_points[1]["source_excerpt"] == "cash flow 2"
