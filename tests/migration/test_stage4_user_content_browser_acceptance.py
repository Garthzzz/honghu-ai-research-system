from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_browser_acceptance_keeps_credentials_out_of_cli_and_evidence() -> None:
    source = (
        ROOT / "tools/migration/stage4_user_content_browser_acceptance.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    options = {
        constant.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for constant in node.args
        if isinstance(constant, ast.Constant) and isinstance(constant.value, str)
    }
    assert "--password" not in options
    assert "keyring.get_password" in source
    assert '"credential_recorded": False' in source
    assert "tls_verified_before_browser" in source


def test_browser_acceptance_exercises_real_ui_and_cleans_with_soft_delete() -> None:
    source = (
        ROOT / "tools/migration/stage4_user_content_browser_acceptance.py"
    ).read_text(encoding="utf-8")
    assert "sync_playwright" in source
    assert ".an-auth-login" in source
    assert "details.an-editor" in source
    assert ".an-add-note" in source
    assert ".an-note-body" in source
    assert "method:'DELETE'" in source
    assert "soft_delete_verified" in source
    assert "screenshot_sha256" in source
