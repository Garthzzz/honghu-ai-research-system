from __future__ import annotations

import hashlib
import json

import pytest

from tools.pipeline.apply_fiber_company_production_delta import (
    _canonical_listing_status,
    _load_mapping,
    _remap_source_references,
    _repair_legacy_utf8,
    _resolve_financial_security_readonly,
)


def test_company_identity_listing_status_is_canonical_not_display_text() -> None:
    assert _canonical_listing_status("601869.SH", "A股", "上市") == "a_share"
    assert _canonical_listing_status("GLW", "美股", "上市") == "us"
    assert _canonical_listing_status("5802.T", "其他", "上市") == "tse"
    assert _canonical_listing_status("PRY.MI", "其他", "上市") == "other_listed"
    assert _canonical_listing_status("000836.SZ", "其他", "已退市") == "delisted"


def test_financial_security_is_resolved_readonly_and_exactly() -> None:
    security = (
        187, 199, "长飞光纤", "601869.SH", "A股", "上市", "CNY",
        None, None, "verified",
    )
    link = (199, 187, "canonical")

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Connection:
        def __init__(self) -> None:
            self.sql = []

        def execute(self, sql, params):
            self.sql.append(sql)
            assert params == (199,)
            return Result([link] if "company_link" in sql else [security])

    connection = Connection()
    security_id = _resolve_financial_security_readonly(connection, {
        "research_company_id": 199,
        "canonical_name": "长飞光纤",
        "ticker": "601869.SH",
        "market": "A股",
        "listing_status": "上市",
        "reporting_currency": "CNY",
        "name_en": None,
        "fiscal_year_end": None,
        "identity_status": "verified",
    })
    assert security_id == 187
    assert all(sql.lstrip().startswith("SELECT") for sql in connection.sql)
    assert all("UPDATE" not in sql.upper() for sql in connection.sql)
    assert all("INSERT" not in sql.upper() for sql in connection.sql)


@pytest.mark.parametrize("extra_security,dangling_link", [(True, False), (False, True)])
def test_financial_security_rejects_unlinked_or_dangling_duplicate_identity(
    extra_security: bool, dangling_link: bool
) -> None:
    security = (
        187, 199, "长飞光纤", "601869.SH", "A股", "上市", "CNY",
        None, None, "verified",
    )
    securities = [security] + ([(999, *security[1:])] if extra_security else [])
    links = [(199, 187, "canonical")] + ([(199, 999, "canonical")] if dangling_link else [])

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Connection:
        def execute(self, sql, _params):
            return Result(links if "company_link" in sql else securities)

    with pytest.raises(RuntimeError, match="missing or ambiguous"):
        _resolve_financial_security_readonly(Connection(), {
            "research_company_id": 199, "canonical_name": "长飞光纤",
            "ticker": "601869.SH", "market": "A股", "listing_status": "上市",
            "reporting_currency": "CNY", "name_en": None,
            "fiscal_year_end": None, "identity_status": "verified",
        })


def test_legacy_utf8_identity_is_repaired_only_when_reversible() -> None:
    damaged = "长飞光纤".encode("utf-8").decode("cp1252")
    assert _repair_legacy_utf8(damaged) == "长飞光纤"
    assert _repair_legacy_utf8("Corning") == "Corning"


def test_nested_profile_source_references_are_remapped_exactly() -> None:
    payload = [
        {"period": "2025", "source_ids": [1135, 1148]},
        {"source_id": 1149, "detail": {"source_id": 1135}},
    ]
    assert _remap_source_references(
        payload,
        {1135: 1132, 1148: 1141, 1149: 1142},
    ) == [
        {"period": "2025", "source_ids": [1132, 1141]},
        {"source_id": 1142, "detail": {"source_id": 1132}},
    ]


def test_mapping_bytes_and_hash_are_frozen_by_one_read() -> None:
    raw = json.dumps({
        "schema_version": "fiber.company_source_mapping.v1",
        "delta_sha256": "d" * 64,
        "sources": {"source:a": 1126},
    }).encode("utf-8")

    class OneReadPath:
        def __init__(self) -> None:
            self.reads = 0

        def read_bytes(self) -> bytes:
            self.reads += 1
            if self.reads > 1:
                raise AssertionError("mapping must not be read twice")
            return raw

    path = OneReadPath()
    mapping, mapping_sha256 = _load_mapping(path, "d" * 64)  # type: ignore[arg-type]
    assert mapping == {"source:a": 1126}
    assert mapping_sha256 == hashlib.sha256(raw).hexdigest()
    assert path.reads == 1
