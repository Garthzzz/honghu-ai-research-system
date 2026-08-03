from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.pipeline.paper_paths import (
    MAX_FILENAME_CHARS,
    filesystem_path,
    normalize_new_paper_file,
    paper_path_violations,
    proposed_paper_path,
)


def test_long_report_name_keeps_real_extension_and_adds_stable_hash(
    tmp_path: Path,
) -> None:
    papers = tmp_path / "papers" / "industry"
    papers.mkdir(parents=True)
    source = papers / (
        "2026-07-14_broker_company_公司（002463.SZ）："
        + "非常长的研究报告标题" * 12
        + ".pdf"
    )
    expected = proposed_paper_path(source, project_root=tmp_path)
    repeated = proposed_paper_path(source, project_root=tmp_path)

    assert expected == repeated
    assert expected.suffix == ".pdf"
    assert expected.name.endswith(".pdf")
    assert len(expected.name) <= MAX_FILENAME_CHARS
    assert "__" in expected.stem


def test_portable_sanitization_does_not_add_hash_when_truncation_is_unneeded(
    tmp_path: Path,
) -> None:
    papers = tmp_path / "papers"
    papers.mkdir()
    source = papers / "Short  report.pdf"

    assert proposed_paper_path(
        source,
        project_root=tmp_path,
    ).name == "Short report.pdf"


def test_new_unreferenced_paper_is_renamed_before_ingest(tmp_path: Path) -> None:
    papers = tmp_path / "papers" / "industry"
    papers.mkdir(parents=True)
    source = papers / (("long title " * 10).strip() + ".pdf")
    source.write_bytes(b"%PDF-test")

    safe = normalize_new_paper_file(source, project_root=tmp_path)

    assert not source.exists()
    assert safe.is_file()
    assert safe.read_bytes() == b"%PDF-test"
    assert paper_path_violations(
        tmp_path / "papers",
        project_root=tmp_path,
    ) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH regression")
def test_violation_scan_sees_file_beyond_legacy_max_path(tmp_path: Path) -> None:
    papers = tmp_path / "papers" / "industry"
    papers.mkdir(parents=True)
    source = papers / (("very-long-report-title-" * 8) + ".pdf")
    filesystem_path(source).write_bytes(b"%PDF-long-path")
    assert len(str(source)) > 260

    violations = paper_path_violations(
        tmp_path / "papers",
        project_root=tmp_path,
    )

    assert source.absolute() in violations
