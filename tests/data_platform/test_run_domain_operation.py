from __future__ import annotations

from tools.data_platform.run_domain_operation import (
    install_operation_context,
    trusted_os_principal,
)


def test_domain_runner_actor_is_derived_from_os_not_client_text() -> None:
    principal = trusted_os_principal()
    assert principal.startswith("principal:os:")
    assert len(principal) > len("principal:os:")


def test_business_window_operation_identity_is_retry_stable(monkeypatch) -> None:
    monkeypatch.delenv("HONGHU_OPERATION_ID", raising=False)
    first = install_operation_context(
        cutover_unit="dynamic_intelligence",
        operation_scope="scheduled_tick",
        logical_window="2026-08-17T08:00",
    )
    second = install_operation_context(
        cutover_unit="dynamic_intelligence",
        operation_scope="scheduled_tick",
        logical_window="2026-08-17T08:00",
    )
    assert first == second
    assert first == "dynamic_intelligence:scheduled_tick:2026-08-17T08:00"


def test_explicit_controlled_runner_identity_is_never_replaced(monkeypatch) -> None:
    monkeypatch.setenv("HONGHU_OPERATION_ID", "upstream-checkpoint-42")
    assert install_operation_context(
        cutover_unit="sentiment_analytics",
        operation_scope="retail_window",
        logical_window="2026-08-17:morning",
    ) == "upstream-checkpoint-42"
