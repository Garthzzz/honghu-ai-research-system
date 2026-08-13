from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_acceptance_never_accepts_password_on_command_line() -> None:
    source = (ROOT / "tools/migration/stage4_user_content_acceptance.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    option_strings = {
        constant.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for constant in node.args
        if isinstance(constant, ast.Constant) and isinstance(constant.value, str)
    }
    assert "--password" not in option_strings
    assert "keyring.get_password" in source
    assert '"credential_recorded": False' in source


def test_acceptance_has_separate_s2_first_mutation_and_s3_stress() -> None:
    source = (ROOT / "tools/migration/stage4_user_content_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert '_health(client, args.base_url, args.expected_commit, "S2")' in source
    assert '_health(control, args.base_url, args.expected_commit, "S3")' in source
    assert "uncertain-response replay was not idempotent" in source
    assert "plaintext 8080 mutation was not rejected" in source
    assert "ThreadPoolExecutor" in source
    assert "soft_deleted_count" in source
