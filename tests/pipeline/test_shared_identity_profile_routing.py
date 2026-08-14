from __future__ import annotations

import json

import pytest

from tools.data_platform.local_authority_fence import LocalAuthorityFenceError
from tools.data_platform.routing import AuthorityState, Backend, CutoverRoute
from tools.pipeline import ensure_listed_company_profile as profile


class _Repository:
    calls: list[dict] = []

    def __init__(self, *_args):
        pass

    def ensure_listed_company(self, **payload):
        self.calls.append(payload)
        return {
            "company_id": 901,
            "financial_security_id": 902,
            "stable_key": "company:security:688041.SH:venue:shanghai",
            "created": True,
        }


def test_profile_provisioning_uses_explicit_postgresql_route_without_sqlite_fallback(
    monkeypatch,
) -> None:
    route = CutoverRoute(
        cutover_unit="shared_identity",
        backend=Backend.POSTGRESQL_PRODUCTION,
        writer_operation="shared_identity_mutation",
        transaction_boundary="one shared identity mutation",
        authority_state=AuthorityState.S3,
        sqlite_writer_enabled=False,
        production_postgresql_enabled=True,
        writer_identity="shared-writer",
        cutover_epoch="shared-epoch",
        approval_reference="approval:shared",
    )
    _Repository.calls = []
    monkeypatch.setattr(profile, "load_cutover_route", lambda *_a, **_k: route)
    monkeypatch.setattr(profile, "load_postgres_runtime_settings", lambda _p: object())
    monkeypatch.setattr(
        profile, "build_postgres_connection_factory", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(profile, "PostgresSharedIdentityRepository", _Repository)
    monkeypatch.setenv("HONGHU_SHARED_IDENTITY_POSTGRES_CONFIG", "runtime.json")

    result = profile.ensure_listed_company_profile(
        canonical_name="海光信息",
        ticker="688041.SH",
        market="A股",
        listing_status="listed",
        verification_source_ref="exchange:688041.SH",
        aliases=["海光信息", "Hygon"],
        confirm_live=True,
        idempotency_key="company-create-688041",
        actor="trusted-operator",
    )
    assert result["company_id"] == 901
    assert result["company_url"] == "/company/901"
    assert _Repository.calls == [
        {
            "canonical_name": "海光信息",
            "ticker": "688041.SH",
            "market": "A股",
            "listing_status": "listed",
            "verification_source_ref": "exchange:688041.SH",
            "aliases": ["海光信息", "Hygon"],
            "idempotency_key": "company-create-688041",
            "actor": "trusted-operator",
        }
    ]


def test_profile_provisioning_fails_closed_when_live_marker_retires_sqlite(
    monkeypatch, tmp_path
) -> None:
    route = CutoverRoute(
        cutover_unit="shared_identity",
        backend=Backend.SQLITE_TRANSITION,
        writer_operation="shared_identity_mutation",
        transaction_boundary="one shared identity mutation",
        authority_state=AuthorityState.S0,
        sqlite_writer_enabled=True,
        production_postgresql_enabled=False,
    )
    data_root = tmp_path / "data"
    marker = data_root / "authority" / "shared_identity.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "schema_version": "honghu.local_authority_fence.v1",
                "cutover_unit": "shared_identity",
                "authority_state": "S3",
                "authoritative_backend": "postgresql_production",
                "authority_evidence_sha256": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(profile, "load_cutover_route", lambda *_a, **_k: route)

    with pytest.raises(LocalAuthorityFenceError, match="SQLite writer is retired"):
        profile.ensure_listed_company_profile(
            canonical_name="Test Company",
            ticker="TEST.US",
            market="US",
            listing_status="listed",
            verification_source_ref="exchange:TEST.US",
            research_db_path=data_root / "research.db",
            financial_db_path=data_root / "financial.db",
            confirm_live=True,
        )

    assert not (data_root / "research.db").exists()
    assert not (data_root / "financial.db").exists()
