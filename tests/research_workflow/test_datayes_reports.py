from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from tools.pipeline.paper_source_manifest import (
    SCHEMA_VERSION,
    enrich_claim_sources,
    hash_file,
    load_manifests,
    opportunity_source_from_manifest,
    write_manifest,
)
from tools.opportunity_lens.run_pack_builder import RunPackBuilder
from tools.research_core.brief import compile_research_brief
from tools.research_core.config import resolve_track_config
from tools.research_sources.datayes_reports import (
    ReportCandidate,
    ReportSearchRequest,
    _resolve_profile_dir,
    _validate_pdf,
    classify_publisher,
    select_candidates,
)


def _write_pdf(path: Path, pages: int) -> None:
    document = fitz.open()
    try:
        for index in range(pages):
            page = document.new_page()
            page.insert_text((72, 72), f"page {index + 1}")
        document.save(path)
    finally:
        document.close()


def test_datayes_provider_contract_is_shared_by_all_tracks() -> None:
    for track in ("a", "b", "c"):
        profile = resolve_track_config(track)
        provider = profile["search_channels"]["report_providers"][0]
        assert provider["provider_id"] == "datayes_playwright"
        assert provider["credential_policy"] == "windows_credential_manager_keyring"
        assert provider["search_field"] == "title_only"
        assert provider["company_max_age_days"] == 183
        assert provider["industry_max_age_days"] == 366
        assert provider["industry_min_pages"] == 20
        assert provider["aggregator_is_not_independent_publisher"] is True

    brief = compile_research_brief(
        track="c",
        title="测试",
        research_question="测试行业供需",
    )
    provider = brief.search_plan["report_provider_contract"][0]
    assert provider["provider_id"] == "datayes_playwright"


def test_search_request_applies_company_and_industry_windows() -> None:
    company = ReportSearchRequest("正泰电器", "光伏", "company", "2026-08-01")
    industry = ReportSearchRequest("碳酸锂 深度", "碳酸锂", "industry", "2026-08-01")
    assert company.cutoff_date.isoformat() == "2026-01-30"
    assert company.minimum_pages == 0
    assert industry.cutoff_date.isoformat() == "2025-07-31"
    assert industry.minimum_pages == 20


def test_candidate_selection_requires_foreign_and_domestic_recommendations() -> None:
    request = ReportSearchRequest(
        "碳酸锂 深度",
        "碳酸锂",
        "industry",
        "2026-08-01",
        domestic_target=1,
        foreign_target=1,
    )
    rows = [
        ReportCandidate("碳酸锂行业深度研究", "中信证券", "2026-07-01", 35, "https://r.datayes.com/report/1", "domestic", "domestic_recommended", request.query),
        ReportCandidate("全球碳酸锂行业深度", "Goldman Sachs", "2026-06-01", 40, "https://r.datayes.com/report/2", "foreign", "foreign_sell_side", request.query),
        ReportCandidate("碳酸锂行业短评", "华泰证券", "2026-07-20", 8, "https://r.datayes.com/report/3", "domestic", "domestic_recommended", request.query),
        ReportCandidate("碳酸锂行业深度旧报告", "Citi", "2025-01-01", 50, "https://r.datayes.com/report/4", "foreign", "foreign_sell_side", request.query),
    ]
    selected, summary = select_candidates(rows, request)
    assert len(selected) == 2
    assert {item.publisher_origin for item in selected} == {"domestic", "foreign"}
    assert summary["domestic_recommended_selected"] == 1
    assert summary["foreign_selected"] == 1
    assert classify_publisher("Morgan Stanley") == "foreign"
    assert classify_publisher("中金公司") == "domestic"


def test_domestic_title_result_is_download_fallback_but_not_recommendation_quota() -> None:
    request = ReportSearchRequest(
        "碳酸锂 深度",
        "碳酸锂",
        "industry",
        "2026-08-01",
        domestic_target=1,
        foreign_target=1,
    )
    rows = [
        ReportCandidate("碳酸锂行业深度报告", "浙商证券", "2026-06-16", 43, "https://r.datayes.com/details/report/1", "domestic", "search_result", request.query),
        ReportCandidate("中国电池材料与碳酸锂", "Citi", "2026-06-01", 28, "https://r.datayes.com/details/report/2", "foreign", "foreign_sell_side", request.query),
    ]
    selected, summary = select_candidates(rows, request)
    assert len(selected) == 2
    assert summary["domestic_recommended_selected"] == 0
    assert summary["domestic_title_fallback_selected"] == 1
    assert summary["domestic_reference_selected"] == 1


def test_pdf_validation_enforces_industry_page_floor(tmp_path: Path) -> None:
    report = tmp_path / "report.pdf"
    _write_pdf(report, 20)
    pages, size_bytes, digest = _validate_pdf(report, minimum_pages=20)
    assert pages == 20
    assert size_bytes == report.stat().st_size
    assert digest == hash_file(report)
    with pytest.raises(ValueError, match="未达到门槛"):
        _validate_pdf(report, minimum_pages=21)


def test_source_manifest_enriches_ab_claims_without_overwriting_explicit_fields(
    tmp_path: Path,
) -> None:
    root = tmp_path / "industry_demo"
    papers = root / "papers" / "碳酸锂"
    manifests = papers / "_source_manifests"
    manifests.mkdir(parents=True)
    report = papers / "report.pdf"
    _write_pdf(report, 20)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provider": "datayes_playwright",
        "entries": [{
            "relative_path": "papers/碳酸锂/report.pdf",
            "sha256": hash_file(report),
            "title": "碳酸锂行业深度",
            "publisher": "Goldman Sachs",
            "publish_date": "2026-06-01",
            "source_url": "https://r.datayes.com/report/2",
            "report_scope": "industry",
            "publisher_origin": "foreign",
            "fetch_method": "playwright_datayes",
            "independence_key": "sell_side:goldmansachs:碳酸锂行业深度:20260601",
        }],
    }
    write_manifest(
        manifests / "datayes_test.json",
        project_root=root,
        payload=payload,
    )
    documents = [{
        "sources": [{
            "source_file": "report.pdf",
            "quality_tier": 1,
        }],
    }]
    assert enrich_claim_sources(
        documents,
        papers_subdir="碳酸锂",
        project_root=root,
    ) == 1
    source = documents[0]["sources"][0]
    assert source["publisher"] == "Goldman Sachs"
    assert source["source_url"] == "https://r.datayes.com/report/2"
    assert source["source_channel"] == "report"
    assert source["source_subtype"] == "foreign_sell_side_industry_report"
    assert source["quality_tier"] == 1
    serialized = json.dumps(source, ensure_ascii=False)
    assert "cookie" not in serialized.lower()
    assert "password" not in serialized.lower()


def test_repeated_download_manifest_reuses_same_source_identity(tmp_path: Path) -> None:
    root = tmp_path / "industry_demo"
    papers = root / "papers" / "碳酸锂"
    manifests = papers / "_source_manifests"
    manifests.mkdir(parents=True)
    report = papers / "report.pdf"
    _write_pdf(report, 20)
    entry = {
        "relative_path": "papers/碳酸锂/report.pdf",
        "sha256": hash_file(report),
        "title": "碳酸锂行业深度",
        "publisher": "浙商证券",
        "publish_date": "2026-06-16",
        "source_url": "https://r.datayes.com/details/report/1",
        "report_scope": "industry",
        "publisher_origin": "domestic",
        "fetch_method": "playwright_datayes",
        "independence_key": "sell_side:浙商证券:碳酸锂行业深度:20260616",
    }
    for index, timestamp in enumerate(("2026-08-01T01:00:00Z", "2026-08-01T02:00:00Z")):
        payload = {
            "schema_version": SCHEMA_VERSION,
            "provider": "datayes_playwright",
            "entries": [entry | {"downloaded_at_utc": timestamp}],
        }
        write_manifest(
            manifests / f"datayes_{index}.json",
            project_root=root,
            payload=payload,
        )
    loaded = load_manifests(papers, project_root=root)
    assert list(loaded) == ["papers/碳酸锂/report.pdf"]


def test_c_track_manifest_source_requires_translation_and_stays_pending(
    tmp_path: Path,
) -> None:
    root = tmp_path / "industry_demo"
    papers = root / "papers" / "碳酸锂"
    papers.mkdir(parents=True)
    report = papers / "foreign.pdf"
    _write_pdf(report, 20)
    entry = {
        "relative_path": "papers/碳酸锂/foreign.pdf",
        "sha256": hash_file(report),
        "title": "Lithium industry",
        "publisher": "Citi",
        "publish_date": "2026-06-01",
        "source_url": "https://r.datayes.com/details/report/2",
        "language": "en",
        "independence_key": "sell_side:citi:lithiumindustry:20260601",
        "independence_rationale": "按底层券商、标题和日期去重。",
    }
    with pytest.raises(ValueError, match="excerpt_zh"):
        opportunity_source_from_manifest(
            entry,
            project_root=root,
            ref="SRC-CITI-LITHIUM",
            excerpt="Lithium demand is rising.",
        )
    builder = RunPackBuilder(
        slug="test",
        research_question="测试",
        intake={},
    )
    builder.add_paper_manifest_source(
        entry,
        project_root=root,
        ref="SRC-CITI-LITHIUM",
        excerpt="Lithium demand is rising.",
        excerpt_zh="锂需求正在增长。",
        title_zh="锂行业",
    )
    assert builder.sources[0]["source_review_status"] == "pending"
    assert builder.sources[0]["document_sha256"] == hash_file(report)


def test_profile_path_cannot_escape_secrets(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="secrets"):
        _resolve_profile_dir(tmp_path / "profile")


def test_datayes_connector_uses_browser_ui_not_site_api() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "research_sources"
        / "datayes_reports.py"
    ).read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "page.evaluate(" not in source
    assert "expect_download" in source
    assert "get_by_role" in source
    assert ".intro-box .report-download:visible" in source
