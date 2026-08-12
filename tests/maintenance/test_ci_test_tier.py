from __future__ import annotations

import json
from pathlib import Path

from tools.ci import run_test_tier


def test_core_test_runner_uses_only_the_authoritative_tests_root(
    tmp_path: Path, monkeypatch
) -> None:
    ignored = tmp_path / "tests" / "governed.py"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("", encoding="utf-8")
    manifest = tmp_path / "tiers.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "honghu.ci_test_tiers.v1",
                "core": {"ignore_modules": ["tests/governed.py"]},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(run_test_tier, "ROOT", tmp_path)
    captured: dict[str, object] = {}

    def fake_call(command: list[str], cwd: Path) -> int:
        captured["command"] = command
        captured["cwd"] = cwd
        return 0

    monkeypatch.setattr(run_test_tier.subprocess, "call", fake_call)
    assert run_test_tier.main(["--manifest", str(manifest)]) == 0
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:5] == [run_test_tier.sys.executable, "-m", "pytest", "-q", "tests"]
    assert "--ignore=tests/governed.py" in command
    assert captured["cwd"] == tmp_path
