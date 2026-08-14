from __future__ import annotations

import json

import pytest


def test_financial_default_route_remains_sqlite_s0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HONGHU_FINANCIAL_DATA_ROUTE_CONFIG", raising=False)
    from tools.financial.db import _postgres_route

    route, Backend = _postgres_route()
    assert route.backend is Backend.SQLITE_TRANSITION
    assert route.authority_state.value == "S0"


def test_financial_postgresql_route_fences_legacy_writer(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = {
        "schema_version": "honghu.cutover_route.v1",
        "cutover_unit": "financial_data",
        "route_revision": 2,
        "authority_state": "S3",
        "backend": "postgresql_production",
        "sqlite_writer_enabled": False,
        "production_postgresql_enabled": True,
        "writer_identity": "financial-writer-v1",
        "cutover_epoch": "epoch-v1",
        "approval_reference": "approval-v1",
        "writer_operation": "financial_data_mutation",
        "transaction_boundary": "one financial mutation",
    }
    path = tmp_path / "route.json"
    path.write_text(json.dumps(route), encoding="utf-8")
    monkeypatch.setenv("HONGHU_FINANCIAL_DATA_ROUTE_CONFIG", str(path))
    from tools.data_platform.financial_data import FinancialDataWriterFenced
    from tools.financial.db import connect

    with pytest.raises(FinancialDataWriterFenced):
        connect(tmp_path / "should-not-exist.db", readonly=False)
    assert not (tmp_path / "should-not-exist.db").exists()
