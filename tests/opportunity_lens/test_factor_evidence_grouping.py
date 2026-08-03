from __future__ import annotations

from tools.opportunity_lens.manual_run_loader import (
    _build_evidence_weighting,
    _collect_factor_evidence_refs,
    _dedupe_evidence_refs_by_group,
)
from tools.opportunity_lens.score_trace import _factor_human_explanation, _translation_for_exact_excerpt


def test_v2_factor_does_not_inherit_entity_wide_evidence() -> None:
    entity = {"evidence_ref_uri_list": ["opp://source/99"]}
    factor = {
        "evidence_ref_uri_list": ["opp://source/1"],
        "source_context_refs": ["opp://source/2"],
        "information_points": [{"evidence_ref": "opp://source/3"}],
    }

    assert _collect_factor_evidence_refs(entity, factor) == [
        "opp://source/1",
        "opp://source/2",
        "opp://source/3",
    ]
    assert _collect_factor_evidence_refs(
        entity, factor, include_entity_refs=True
    )[-1] == "opp://source/99"


def test_factor_gate_counts_independence_groups_not_source_uris() -> None:
    refs = ["opp://source/1", "opp://source/2", "opp://source/3"]
    groups = {
        "opp://source/1": "issuer:a:annual-report",
        "opp://source/2": "issuer:a:annual-report",
        "opp://source/3": "regulator:b:filing",
    }

    counted = _dedupe_evidence_refs_by_group(refs, groups)
    assert counted == ["opp://source/1", "opp://source/3"]

    weighting = _build_evidence_weighting(
        {"score_adjusted": 60},
        counted,
        required_refs=3,
        evidence_group_by_ref=groups,
    )
    assert weighting["available_group_count"] == 2
    assert weighting["minimum_required_groups"] == 3
    assert weighting["gate_verdict"] == "blocked"
    assert [item["independence_key"] for item in weighting["items"]] == [
        "issuer:a:annual-report",
        "regulator:b:filing",
    ]


def test_translation_never_falls_back_across_distinct_facts() -> None:
    assert (
        _translation_for_exact_excerpt(
            "抛光机数量较少，是产能瓶颈。",
            "SOI需要氧化、注入和键合工序。",
            "SOI requires oxidation, implantation and bonding.",
        )
        == ""
    )
    assert (
        _translation_for_exact_excerpt(
            "The fab targets 30,000 wafers per month.",
            "该工厂目标月产能为3万片。",
            "Another fact from the same source.",
        )
        == ""
    )
    assert (
        _translation_for_exact_excerpt(
            "The fab targets 30,000 wafers per month.",
            "该工厂目标月产能为3万片。",
            "The fab targets 30,000 wafers per month.",
        )
        == "该工厂目标月产能为3万片。"
    )


def test_factor_page_translates_internal_gate_verdict() -> None:
    row = {
        "factor_code": "demand.downstream_price_momentum",
        "score_status": "insufficient_evidence",
        "coverage": 0.2,
        "confidence": 0.4,
        "factor_trace": {
            "evidence_weighting": {
                "minimum_required_groups": 3,
                "available_group_count": 5,
                "gate_verdict": "pass",
            }
        },
    }
    explanation = _factor_human_explanation(row, [])
    rendered = " ".join(explanation["plain_steps"])
    assert "已满足该数量要求" in rendered
    assert "闸门结论" not in rendered
    assert " pass" not in rendered
