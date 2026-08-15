from __future__ import annotations

from tools.data_platform.run_domain_operation import trusted_os_principal


def test_domain_runner_actor_is_derived_from_os_not_client_text() -> None:
    principal = trusted_os_principal()
    assert principal.startswith("principal:os:")
    assert len(principal) > len("principal:os:")
